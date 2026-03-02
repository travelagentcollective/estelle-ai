import os, json
from dotenv import load_dotenv
from datetime import datetime
import uuid_utils
from llm_provider import call_llm

from sqlalchemy import Column, String, DateTime, Text, select, ForeignKey, Boolean
from sqlalchemy.orm import declarative_base, sessionmaker, relationship
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.sql import func, update


load_dotenv()

DB_DSN = os.getenv("DB_DSN")

ASYNC_DB_URL = DB_DSN.replace("postgresql://", "postgresql+asyncpg://")

COLLECTION_NAME = "estelle_guidelines"

engine = create_async_engine(ASYNC_DB_URL, echo=False) # True para Debugar

AsyncSessionLocal = sessionmaker(
    engine, class_=AsyncSession, expire_on_commit=False
)

Base = declarative_base()

class Thread(Base):
    __tablename__ = "threads"

    id = Column(String, primary_key=True, default=lambda: f"thread_{str(uuid_utils.uuid7())}")
    user_id = Column(String, nullable=False, index=True)
    title = Column(String, nullable=True)
    status = Column(String, default="active")
    summary = Column(Text, nullable=True)
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    messages = relationship("Message", back_populates="thread", cascade="all, delete-orphan")

class Message(Base):
    __tablename__ = "chat_message"

    id = Column(String, primary_key=True, default=lambda: f"message_{str(uuid_utils.uuid7())}")
    thread_id = Column(String, ForeignKey("threads.id"), nullable=False)
    role = Column(String, nullable=False)
    content = Column(Text, nullable=False)
    is_summarized = Column(Boolean, default=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    thread = relationship("Thread", back_populates="messages")

async def init_db():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    print("Tables created succefully.")

async def save_message(session: AsyncSession, thread_id: str, role: str, content: str):
    new_message = Message(
        thread_id=thread_id,
        role=role,
        content=content,
        is_summarized=False
    )
    session.add(new_message)
    await session.commit()

    await session.refresh(new_message)

    try:
        count_query = (
            select(func.count(Message.id))
            .where(Message.thread_id == thread_id)
            .where(Message.is_summarized == False) 
        )
        result = await session.execute(count_query)
        pending_count = result.scalar()
        
        if pending_count >= 15:
            await generate_thread_summary(session, thread_id)

    except Exception as e:
        print(f"Error to verify the summary: {e}")

    return new_message

async def get_messages(session: AsyncSession, thread_id: str, cursor: str = None, limit: int = 10):
    stmt = (
        select(Message).where(Message.thread_id == thread_id).order_by(Message.id.desc()).limit(limit + 1)
    )

    if cursor:
        stmt = stmt.where(Message.id < cursor)

    result = await session.execute(stmt)
    messages = result.scalars().all()

    has_more = len(messages) > limit

    if has_more:
        messages.pop()

    reversed_messages = list(reversed(messages))

    next_cursor = reversed_messages[0].id if messages else None

    return {
        "messages": reversed_messages,
        "next_cursor": next_cursor,
        "has_more": has_more
    }

async def get_user_threads(session: AsyncSession, user_id: str):
    thread_query = (
        select(Thread)
        .where(Thread.user_id == user_id)
        .order_by(Thread.created_at.desc())
    )

    response = await session.execute(thread_query)

    return response.scalars().all()

async def get_or_create_thread(session: AsyncSession, user_id: str, thread_id: str):
    thread = None
    
    if thread_id:
        thread_query = select(Thread).where(Thread.id == thread_id)
        result = await session.execute(thread_query)
        thread = result.scalar_one_or_none()

        if thread and thread.user_id != user_id:
            thread = None

    if not thread:
        new_id = thread_id if (thread_id and len(thread_id) > 20) else f"{uuid_utils.uuid7()}"

        data_atual = datetime.now().strftime("%Y/%m/%d")
        thread = Thread(
            user_id=user_id,
            title=f"Chat on {data_atual}",
            status="active"
        )
        session.add(thread)
        await session.commit()
    
    return thread

async def update_thread_title(session: AsyncSession, user_id: str, thread_id: str, new_thread_title: str):
    thread_query = select(Thread).where(Thread.id == thread_id, Thread.user_id == user_id)
    result = await session.execute(thread_query)
    thread = result.scalar_one_or_none()

    if thread:
        thread.title = new_thread_title
        await session.commit()
        await session.refresh(thread)
        
        return thread
           
    return None

async def remove_thread(session: AsyncSession, user_id: str, thread_id: str):
    thread_query = select(Thread).where(Thread.id == thread_id, Thread.user_id == user_id)
    result = await session.execute(thread_query)
    thread = result.scalar_one_or_none()

    if thread:
        await session.delete(thread)
        await session.commit()
        
        return True
    
    return False

async def mark_messages_as_summarized(session: AsyncSession, thread_id: str):
    stmt = (
        update(Message).
        where(Message.thread_id == thread_id).
        where(Message.is_summarized == False).
        values(is_summarized=True)
    )

    await session.execute(stmt)
    await session.commit()

async def generate_thread_summary(session: AsyncSession, thread_id: str):
    res_thread = await session.execute(select(Thread).where(Thread.id == thread_id))
    thread = res_thread.scalar_one_or_none()
    
    messages_query = await session.execute(
        select(Message.role, Message.content)
        .where(Message.thread_id == thread_id, Message.is_summarized == False)
        .order_by(Message.created_at.asc())
    )

    messages = messages_query.all()

    if not thread or not messages:
        return

    json_messages = json.dumps([{"role": m.role, "content": m.content} for m in messages], ensure_ascii=False)

    prompt = (
        f"You are a memory assistant. Update the conversation summary below..\n"
        f"Previous summary: {thread.summary or 'No history.'}\n"
        f"New interactions (JSON): {json_messages}\n\n"
        f"Generate a new consolidated summary, retaining crucial facts and decisions, in a maximum of 3 sentences."
    )

    llm = call_llm()


    try:
        response = await llm.ainvoke(prompt)
        thread.summary = response.content

        await session.execute(
            update(Message)
            .where(Message.thread_id == thread_id, Message.is_summarized == False)
            .values(is_summarized=True)
        )

        await session.commit()
    except Exception as e:
        await session.rollback()

async def check_and_update_summary(session: AsyncSession, thread_id: str, llm):
    count_stmt = (
        select(func.count(Message.id))
        .where(Message.thread_id == thread_id)
        .where(Message.is_summarized == False)
    )
    result = await session.execute(count_stmt)
    pending_count = result.scalar()

    if pending_count >= 16:
        await generate_thread_summary(session, thread_id, llm)
    else:
        pass

async def count_pending_messages(session: AsyncSession, thread_id: str):
    stmt = (
        select(func.count(Message.id))
        .where(Message.thread_id == thread_id)
        .where(Message.is_summarized == False)
    )
    result = await session.execute(stmt)
    return result.scalar()

async def get_context_for_llm(session: AsyncSession, thread_id: str):
    thread_query = await session.execute(select(Thread).where(Thread.id == thread_id))
    thread = thread_query.scalar_one_or_none()

    messages_query = (select(Message)
                      .where(Message.thread_id == thread_id, Message.is_summarized == False)
                      .order_by(Message.created_at.asc())
                      )
    messages = await session.execute(messages_query)
    recent_messages = messages.scalars().all()

    return {
        "summary": thread.summary if thread else None,
        "recent_messages": recent_messages
    }

