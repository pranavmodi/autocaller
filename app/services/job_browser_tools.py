"""Restricted Playwright actions. The model never receives JavaScript or shell tools."""
from __future__ import annotations

import asyncio
from pathlib import Path
from urllib.parse import urljoin

from pydantic import BaseModel, ConfigDict, Field
from typing import Literal

from app.services.career_search_web import public_url


class BrowserAction(BaseModel):
    model_config = ConfigDict(extra='forbid')
    kind: Literal['goto', 'fill', 'select', 'check', 'press', 'click', 'upload', 'wait',
                  'upload_text', 'email_search', 'verification_code', 'official_source', 'ask',
                  'blocked', 'submit', 'confirmed']
    summary: str = Field(min_length=1, max_length=500)
    element: str | None = Field(None, max_length=40)
    value: str = Field('', max_length=8000)
    checked: bool = True
    url: str = Field('', max_length=2000)
    question: str = Field('', max_length=1500)
    choices: list[str] = Field(default_factory=list, max_length=20)
    evidence: str = Field('', max_length=3000)


FAST_PROGRAM_KINDS = {'fill', 'select', 'check', 'upload'}


class BrowserProgram(BaseModel):
    """A bounded sequence of non-consequential actions from one observation."""
    model_config = ConfigDict(extra='forbid')
    actions: list[BrowserAction] = Field(min_length=2, max_length=12)


def validate_fast_program(program: BrowserProgram, snapshot: dict):
    """Reject anything that could navigate, advance, submit, or target ambiguity."""
    controls = {control['id']: control for frame in snapshot.get('frames', [])
                for control in frame.get('controls', [])}
    seen = set()
    for action in program.actions:
        if action.kind not in FAST_PROGRAM_KINDS:
            raise ValueError('Fast programs are limited to fill, select, check and resume upload actions.')
        if not action.element or action.element in seen:
            raise ValueError('Each fast-program action must target one distinct observed control.')
        seen.add(action.element)
        control = controls.get(action.element)
        if not control or control.get('disabled'):
            raise ValueError('A fast-program control is unavailable in the current observation.')
        if control.get('type') in {'password', 'hidden', 'submit', 'button', 'image', 'reset'}:
            raise ValueError('A fast program cannot use hidden, password, button, or submission controls.')
        if action.kind == 'fill' and control.get('tag') not in {'input', 'textarea'} and not control.get('contenteditable'):
            raise ValueError('Fast-program fill actions require a visible text control.')
        if action.kind == 'select' and control.get('tag') != 'select':
            raise ValueError('Fast-program select actions require a native select control.')
        if action.kind == 'check' and control.get('type') != 'checkbox':
            raise ValueError('Fast-program checks require a native checkbox. Radio and custom choices are handled individually.')
        if action.kind == 'upload' and control.get('type') != 'file':
            raise ValueError('Fast-program uploads are limited to the observed resume file control.')
    return program


class BrowserSession:
    def __init__(self):
        self.engine = self.browser = self.context = self.page = None
        self.elements = {}
        self.snapshot = {}

    async def open(self, url: str):
        from playwright.async_api import async_playwright
        await public_url(url)
        self.engine = await async_playwright().start()
        try:
            self.browser = await self.engine.chromium.launch()
            self.context = await self.browser.new_context(
                viewport={'width': 1280, 'height': 900}, accept_downloads=False,
                service_workers='block')
            # Validate every resource/navigation, including redirects and frames.
            # Disallow access to local services and metadata addresses.
            async def route_request(route):
                try:
                    await asyncio.wait_for(public_url(route.request.url), timeout=10)
                    await route.continue_()
                except Exception:
                    await route.abort()
            await self.context.route('**/*', route_request)
            await self.context.route_web_socket('**/*', lambda ws: ws.close())
            self.page = await self.context.new_page()
            self.context.set_default_timeout(12000)
            await self.page.goto(url, wait_until='domcontentloaded', timeout=45000)
        except BaseException:
            await self.close()
            raise

    async def observe(self, screenshot: Path):
        pages = [page for page in self.context.pages if not page.is_closed()]
        if not pages:
            raise ValueError('The application browser was closed.')
        self.page = pages[-1]
        for handle in self.elements.values():
            try:
                await handle.dispose()
            except Exception:
                pass
        self.elements = {}
        frames = []
        for frame in self.page.frames:
            try:
                # A child document can report visible controls while its containing
                # iframe is hidden. Do not present those as usable page controls.
                ancestor = frame
                hidden = False
                while ancestor.parent_frame is not None:
                    container = await ancestor.frame_element()
                    try:
                        if not await container.is_visible():
                            hidden = True
                            break
                    finally:
                        await container.dispose()
                    ancestor = ancestor.parent_frame
                if hidden:
                    continue
                body_locator = frame.locator('body')
                body = await body_locator.inner_text(timeout=5000)
                # Playwright's ARIA snapshot is a compact representation of the
                # browser accessibility tree. It complements the exact handles
                # below: the model gets semantic page structure while execution
                # remains bound to observed element IDs.
                try:
                    accessibility = (await body_locator.aria_snapshot(timeout=5000))[:24000]
                except Exception:
                    accessibility = ''
                selector = (
                    'a[href],button,input,textarea,select,[role="button"],[role="combobox"],'
                    '[role="checkbox"],[role="radio"],[role="option"],[contenteditable="true"]')
                # Read every control's serializable state in one browser call.
                # Large ATS pages can expose hundreds of controls; asking
                # Playwright for visibility, attributes and values one element
                # at a time makes a read-only observation take several minutes.
                handles = await frame.query_selector_all(selector)
                infos = await frame.eval_on_selector_all(selector, '''els => els.map(e => {
                  const style = window.getComputedStyle(e);
                  const rect = e.getBoundingClientRect();
                  const directlyVisible = (
                    style.display !== 'none' && style.visibility !== 'hidden' &&
                    Number(style.opacity || 1) !== 0 && rect.width > 0 && rect.height > 0);
                  const proxyVisible = ['checkbox', 'radio'].includes(e.type) &&
                    Array.from(e.labels || []).some(label => {
                      const labelStyle = window.getComputedStyle(label);
                      const labelRect = label.getBoundingClientRect();
                      return labelStyle.display !== 'none' &&
                        labelStyle.visibility !== 'hidden' &&
                        Number(labelStyle.opacity || 1) !== 0 &&
                        labelRect.width > 0 && labelRect.height > 0;
                    });
                  const visible = e.type === 'file' || directlyVisible || proxyVisible;
                  return {
                    visible,
                    tag: e.tagName.toLowerCase(), type: e.type || '', role: e.getAttribute('role'),
                    label: e.getAttribute('aria-label') || Array.from(e.labels || []).map(l => l.innerText).join(' ') || e.innerText?.slice(0,300) || e.getAttribute('placeholder') || e.name || '',
                    href: e.href || '', required: !!e.required, disabled: !!e.disabled,
                    accept: e.accept || '',
                    value: e.type === 'password' ? '[redacted]' : (e.value || '').slice(0,8000),
                    checked: !!e.checked, validation: e.validationMessage || '',
                    proxy_visible: proxyVisible && !directlyVisible,
                    contenteditable: e.isContentEditable,
                    options: e.tagName === 'SELECT' ? Array.from(e.options).map(o => ({value:o.value,label:o.label})) : []
                  };
                })''')
                if len(handles) != len(infos):
                    for handle in handles:
                        await handle.dispose()
                    raise ValueError('Page controls changed during inspection; inspect again.')
                controls = []
                for handle, info in zip(handles, infos):
                    if not info.pop('visible'):
                        await handle.dispose()
                        continue
                    key = f'e{len(self.elements)}'
                    self.elements[key] = handle
                    controls.append({'id': key, **info})
                frames.append({'url': frame.url, 'text': body[:24000],
                               'accessibility': accessibility, 'controls': controls})
            except Exception:
                frames.append({'url': frame.url, 'error': 'Frame not readable; inspect again or request help.'})
        password_fields = self.page.locator('input[type="password"]')
        await self.page.screenshot(path=str(screenshot), mask=[password_fields], timeout=15000)
        self.snapshot = {'url': self.page.url, 'title': await self.page.title(), 'frames': frames}
        return self.snapshot

    def control(self, element):
        for frame in self.snapshot.get('frames', []):
            for control in frame.get('controls', []):
                if control['id'] == element:
                    return control
        raise ValueError('The selected control is no longer in the current page snapshot.')

    async def execute(self, action: BrowserAction, resume: Path):
        if action.kind == 'wait':
            await asyncio.sleep(2)
            return
        if action.kind == 'goto':
            links = [c['href'] for f in self.snapshot.get('frames', [])
                     for c in f.get('controls', []) if c.get('href')]
            if action.url not in links:
                raise ValueError('Navigation must use a link observed on the current page.')
            await public_url(action.url)
            await self.page.goto(action.url, wait_until='domcontentloaded', timeout=45000)
            return
        control = self.control(action.element)
        if control['type'] == 'password':
            raise ValueError('Password entry requires manual completion outside this worker.')
        handle = self.elements[action.element]
        if action.kind == 'fill':
            await handle.fill(action.value)
        elif action.kind == 'select':
            await handle.select_option(value=action.value)
        elif action.kind == 'check':
            # Oracle and similar ATS pages hide a native checkbox behind a
            # visible associated label. It is still an exact observed input,
            # but Playwright needs a forced native check because the input's
            # own box is intentionally transparent or zero-sized.
            await handle.set_checked(action.checked, force=bool(control.get('proxy_visible')))
        elif action.kind == 'press':
            # Keep keyboard recovery narrow: these keys can commit or dismiss a
            # custom combobox without granting arbitrary keyboard control.
            if control.get('role') != 'combobox' or action.value not in {
                    'Enter', 'ArrowDown', 'ArrowUp', 'Escape'}:
                raise ValueError('Keyboard actions are limited to safe keys on an observed combobox.')
            await handle.press(action.value)
        elif action.kind == 'upload':
            if control['type'] != 'file':
                raise ValueError('Choose a file upload control for the selected resume.')
            await handle.set_input_files(str(resume))
        elif action.kind == 'upload_text':
            if control['type'] != 'file':
                raise ValueError('Choose the exact file upload control for this written response.')
            accepted = (control.get('accept') or '').lower()
            if accepted and '.txt' not in accepted and 'text/plain' not in accepted:
                raise ValueError('This response field does not accept a plain-text attachment.')
            response = action.value.strip()
            if len(response) < 80:
                raise ValueError('The generated application response is too short to upload.')
            attachment = resume.parent / 'Pranav_Modi_Application_Response.txt'
            attachment.write_text(response + '\n', encoding='utf-8')
            attachment.chmod(0o600)
            await handle.set_input_files(str(attachment))
        elif action.kind in {'click', 'submit'}:
            if action.kind == 'click' and control.get('tag') == 'a' and control.get('href'):
                from playwright.async_api import TimeoutError as PlaywrightTimeoutError
                previous_url = self.page.url
                try:
                    await handle.click()
                except PlaywrightTimeoutError:
                    # Some ATS cards place a text layer over their observed
                    # anchor, so a physical click never reaches the link. If
                    # navigation did not already happen, follow only the exact
                    # public href captured in the current observation.
                    if self.page.url != previous_url:
                        return
                    target = urljoin(previous_url, control['href'])
                    await public_url(target)
                    await self.page.goto(target, wait_until='domcontentloaded', timeout=45000)
            else:
                await handle.click()
        else:
            raise ValueError('This action is not a browser interaction.')

    async def execute_program(self, program: BrowserProgram, resume: Path):
        """Execute a prevalidated input-only program against one observation.

        The program deliberately cannot navigate or submit. If a site changes
        location as a side effect, execution stops immediately and the worker
        must observe the new page before doing anything else.
        """
        validate_fast_program(program, self.snapshot)
        initial_url = self.page.url
        completed = []
        for index, action in enumerate(program.actions):
            await self.execute(action, resume)
            completed.append({'index': index, 'kind': action.kind,
                              'element': action.element, 'status': 'completed'})
            if self.page.url != initial_url:
                raise ValueError('A fast form program caused navigation and stopped before any further action.')
        return completed

    async def human_action(self, kind: str, *, x: float | None = None,
                           y: float | None = None, value: str = '',
                           key: str = '', delta_y: float = 0):
        """Perform one operator-directed action in the existing page.

        This deliberately accepts no selector or JavaScript. Coordinates refer
        to the exact 1280x900 screenshot the operator was shown. Text is used
        only for this call and is never added to a browser snapshot or event.
        """
        if not self.page or self.page.is_closed():
            raise ValueError('The application browser is no longer open.')
        if kind == 'click':
            if x is None or y is None or not (0 <= x <= 1280 and 0 <= y <= 900):
                raise ValueError('Click coordinates must be inside the current browser frame.')
            await self.page.mouse.click(x, y)
        elif kind in {'type', 'replace'}:
            if kind == 'replace':
                await self.page.keyboard.press('Control+A')
            await self.page.keyboard.insert_text(value)
        elif kind == 'press':
            allowed = {
                'Tab', 'Shift+Tab', 'Enter', 'Escape', 'Backspace', 'Delete',
                'ArrowUp', 'ArrowDown', 'ArrowLeft', 'ArrowRight', 'Space',
                'Home', 'End', 'PageUp', 'PageDown',
            }
            if key not in allowed:
                raise ValueError('That keyboard key is not available in human control.')
            await self.page.keyboard.press(key)
        elif kind == 'scroll':
            if not -1800 <= delta_y <= 1800 or delta_y == 0:
                raise ValueError('Scroll distance is outside the allowed range.')
            await self.page.mouse.wheel(0, delta_y)
        else:
            raise ValueError('Unsupported human browser action.')
        await self.page.wait_for_timeout(250)

    async def close(self):
        try:
            if self.browser:
                await self.browser.close()
        finally:
            if self.engine:
                await self.engine.stop()
