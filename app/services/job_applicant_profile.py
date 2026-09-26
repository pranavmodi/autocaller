"""Operator-confirmed answers reusable across job applications, with provenance."""
from __future__ import annotations

import hashlib
import json
from typing import Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy import Boolean, DateTime, Integer, String, Text, select
from sqlalchemy.dialects.postgresql import JSONB, insert
from sqlalchemy.orm import Mapped, mapped_column

from app.services import job_agent as core

Scope = Literal['contextual', 'global', 'country', 'company', 'role', 'application']


class ApplicantAnswer(core.Base):
    __tablename__ = 'job_agent_applicant_answers'
    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    source_key: Mapped[str] = mapped_column(String(64), unique=True)
    question: Mapped[str] = mapped_column(Text)
    answer: Mapped[str] = mapped_column(Text)
    scope: Mapped[str] = mapped_column(String(32), default='contextual')
    scope_value: Mapped[str] = mapped_column(String(1000), default='')
    context: Mapped[dict] = mapped_column(JSONB, default=dict)
    history: Mapped[list] = mapped_column(JSONB, default=list)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    revision: Mapped[int] = mapped_column(Integer, default=1)
    updated_at: Mapped[object] = mapped_column(DateTime(timezone=True), default=core.now)


class ProfileSave(BaseModel):
    model_config = ConfigDict(extra='forbid')
    id: str | None = None
    revision: int = Field(0, ge=0)
    question: str = Field(min_length=1, max_length=8000)
    answer: str = Field(min_length=1, max_length=8000)
    scope: Scope = 'contextual'
    scope_value: str = Field('', max_length=1000)

    @model_validator(mode='after')
    def meaningful(self):
        self.question, self.answer = self.question.strip(), self.answer.strip()
        self.scope_value = self.scope_value.strip()
        if not self.question or not self.answer:
            raise ValueError('Enter both a question or fact label and an answer.')
        if self.scope in {'country', 'company', 'role', 'application'} and not self.scope_value:
            raise ValueError('Specify where this answer applies.')
        return self


class ProfileArchive(BaseModel):
    revision: int = Field(ge=1)


def view(row):
    return {k:getattr(row,k) for k in ('id','question','answer','scope','scope_value','context','revision')} | {
        'updated_at':row.updated_at.isoformat()}


async def list_answers():
    await core.ensure_tables()
    async with core.AsyncSessionLocal() as session:
        rows=(await session.scalars(select(ApplicantAnswer).where(ApplicantAnswer.enabled.is_(True))
            .order_by(ApplicantAnswer.updated_at.desc()))).all()
        return {'items':[view(row) for row in rows]}


async def snapshot(identity):
    items=(await list_answers())['items']
    return [item for item in items if item['scope'] != 'application' or item['scope_value'] == identity]


async def save(body: ProfileSave):
    await core.ensure_tables()
    async with core.AsyncSessionLocal() as session:
        if body.id:
            row=await session.get(ApplicantAnswer,body.id,with_for_update=True)
            if not row or not row.enabled:
                raise ValueError('This saved answer is no longer available. Refresh the profile.')
            if row.revision != body.revision:
                raise ValueError('This answer changed in another window. Reload it before saving.')
            row.history=[*row.history,view(row)]
            row.revision+=1
        else:
            row=ApplicantAnswer(id=uuid4().hex,source_key=uuid4().hex,revision=1,
                context={'source':'profile_editor'},history=[],enabled=True)
            session.add(row)
        for key in ('question','answer','scope','scope_value'):
            setattr(row,key,getattr(body,key))
        row.updated_at=core.now()
        await session.commit()
        return view(row)


async def archive(identity, body: ProfileArchive):
    await core.ensure_tables()
    async with core.AsyncSessionLocal() as session:
        row=await session.get(ApplicantAnswer,identity,with_for_update=True)
        if not row:
            raise ValueError('Saved answer not found.')
        if row.revision != body.revision:
            raise ValueError('This answer changed. Reload before removing it.')
        row.enabled=False
        row.revision+=1
        row.updated_at=core.now()
        await session.commit()
        return {'removed':True,'id':identity}


async def remember(session, candidate_id, posting, answer, *, reusable=True):
    # Exact source identity makes restart/backfill idempotent; no semantic matching.
    source_key=hashlib.sha256(json.dumps([candidate_id,answer['question'],answer['answer'],answer['at']],ensure_ascii=False).encode()).hexdigest()
    statement=insert(ApplicantAnswer).values(id=uuid4().hex,source_key=source_key,
        question=answer['question'],answer=answer['answer'],
        scope='contextual' if reusable else 'application',scope_value='' if reusable else candidate_id,
        context={'source':'application_answer','candidate_id':candidate_id,
            'firm_name':posting.get('firm_name'),'title':posting.get('title'),
            'location':posting.get('location'),'source_url':posting.get('source_url'),
            'answered_at':answer['at']},history=[],enabled=True,revision=1,updated_at=core.now())
    result=await session.execute(statement.on_conflict_do_nothing(index_elements=['source_key']).returning(ApplicantAnswer.id))
    return result.scalar_one_or_none()


async def import_browser_answers():
    from app.services.job_browser import BrowserRun
    await core.ensure_tables()
    added=0
    async with core.AsyncSessionLocal() as session:
        rows=(await session.scalars(select(BrowserRun))).all()
        for row in rows:
            for answer in row.state.get('answers',[]):
                if answer.get('source') == 'profile' or not all(answer.get(k) for k in ('question','answer','at')):
                    continue
                added+=bool(await remember(session,row.candidate_id,row.state['posting'],answer,
                                           reusable=answer.get('remember',True)))
        await session.commit()
    return {'imported':added}
