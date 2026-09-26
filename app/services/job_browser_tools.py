"""Restricted Playwright actions. The model never receives JavaScript or shell tools."""
from __future__ import annotations

import asyncio
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field
from typing import Literal

from app.services.career_search_web import public_url


class BrowserAction(BaseModel):
    model_config = ConfigDict(extra='forbid')
    kind: Literal['goto', 'fill', 'select', 'check', 'click', 'upload', 'wait',
                  'ask', 'blocked', 'submit', 'confirmed']
    summary: str = Field(min_length=1, max_length=500)
    element: str | None = Field(None, max_length=40)
    value: str = Field('', max_length=8000)
    checked: bool = True
    url: str = Field('', max_length=2000)
    question: str = Field('', max_length=1500)
    choices: list[str] = Field(default_factory=list, max_length=20)
    evidence: str = Field('', max_length=3000)


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
                body = await frame.locator('body').inner_text(timeout=5000)
                handles = await frame.query_selector_all(
                    'a[href],button,input,textarea,select,[role="button"],[role="combobox"],'
                    '[role="checkbox"],[role="radio"],[role="option"],[contenteditable="true"]')
                controls = []
                for handle in handles:
                    if not await handle.is_visible() and await handle.get_attribute('type') != 'file':
                        await handle.dispose()
                        continue
                    key = f'e{len(self.elements)}'
                    info = await handle.evaluate('''e => ({
                      tag: e.tagName.toLowerCase(), type: e.type || '', role: e.getAttribute('role'),
                      label: e.getAttribute('aria-label') || Array.from(e.labels || []).map(l => l.innerText).join(' ') || e.innerText?.slice(0,300) || e.getAttribute('placeholder') || e.name || '',
                      href: e.href || '', required: !!e.required, disabled: !!e.disabled,
                      value: e.type === 'password' ? '[redacted]' : (e.value || '').slice(0,8000),
                      checked: !!e.checked, validation: e.validationMessage || '',
                      options: e.tagName === 'SELECT' ? Array.from(e.options).map(o => ({value:o.value,label:o.label})) : []
                    })''')
                    self.elements[key] = handle
                    controls.append({'id': key, **info})
                frames.append({'url': frame.url, 'text': body[:24000], 'controls': controls})
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
            await handle.set_checked(action.checked)
        elif action.kind == 'upload':
            if control['type'] != 'file':
                raise ValueError('Choose a file upload control for the selected resume.')
            await handle.set_input_files(str(resume))
        elif action.kind in {'click', 'submit'}:
            await handle.click()
        else:
            raise ValueError('This action is not a browser interaction.')

    async def close(self):
        try:
            if self.browser:
                await self.browser.close()
        finally:
            if self.engine:
                await self.engine.stop()
