import os
from graph import builder
from database import Message, Thread, AsyncSessionLocal, get_user_threads, get_or_create_thread, save_message, init_db, remove_thread, update_thread_title

from quart import Quart, jsonify, request, abort
from quart_cors import cors

from psycopg_pool import AsyncConnectionPool

from sqlalchemy import select

from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from langchain_core.messages import HumanMessage, AIMessage, SystemMessage


app = Quart(__name__)

app = cors(
    app,
    allow_origin=[
        "http://localhost", 
        "https://localhost", 
        "http://localhost:3000", 
        "https://localhost:3000", 
        "http://localhost:5173", 
        "https://localhost:5173", 
        "https://platform.socialjet.ai", 
        "https://platform.travelagentcollective.com"
        ],
    allow_headers=["Content-Type", "Authorization", "X-API-KEY"],
    allow_methods=["GET", "POST", "PUT", "DELETE", "PATCH", "OPTIONS"]
)

DB_DSN = os.getenv("DB_DSN")

graph = None
pool = None

@app.before_serving
async def setup():
    global graph, pool
    await init_db()

    pool = AsyncConnectionPool(conninfo=DB_DSN, max_size=20, kwargs={"autocommit": True})

    saver = AsyncPostgresSaver(pool)
    
    await saver.setup()

    graph = builder.compile(checkpointer=saver)
    print("🤖 Graph compiled and ready!")

@app.after_serving
async def cleanup():
    global pool
    if pool:
        await pool.close()

@app.before_request
async def verify_api_key():
    if request.method == "OPTIONS":
        return
    
    fe_api_key = request.headers.get("X-API-KEY")
    print(fe_api_key)
    if fe_api_key != os.getenv("X_API_KEY"):
        abort(401, description="Acess denied.")

@app.route('/send_message', methods=['POST'])
async def chat():
    data = await request.get_json()
    user_id = data.get("user_id")
    thread_id = data.get("thread_id")
    user_message = data.get("message")
    role = data.get("role", "user")
    id_images = data.get("idimages", None)


    if not user_message:
        return jsonify({"error": "Message can not be null."}), 400

    async with AsyncSessionLocal() as session:
        thread = await get_or_create_thread(session, user_id, thread_id)
        
        sent_msg_obj = None
        
        if role == "system":
            sent_msg_obj = await save_message(session, thread.id, "system", user_message)
        
            config = {"configurable": {"thread_id": thread.id}}
            
            await graph.aupdate_state(config, {"messages": [SystemMessage(content=user_message)]})

            inputs = {"messages": [SystemMessage(content=user_message)]}       
        elif role == "assistant":
            ai_message_obj = await save_message(session, thread.id, "assistant", user_message)

            config = {"configurable": {"thread_id": thread.id}}
            await graph.aupdate_state(config, {"messages": AIMessage(content=user_message)})
            
            return {
                "thread_id": thread.id,
                "message_id": ai_message_obj.id,
                "response": ai_message_obj.content,
                "created_at": ai_message_obj.created_at,
                "status": "success",
            }
        else:
            content_to_ai = [{"type": "text", "text": user_message}]
            content_to_db = user_message

            if id_images:
                img_id_list = []

                for img in id_images:
                    url = img.get("url")
                    id_img = img.get("idimage")

                    content_to_ai.append({
                        "type": "image_url",
                        "image_url": {"url": url}
                    })

                    img_id_list.append(id_img)

                    content_to_db += f"[Image ID {id_img}]({url})"
                
                if img_id_list:
                    id_img_formated = ", ".join(img_id_list)
                    content_to_ai[0]["text"] += f" (Sent images with ID {id_img_formated})"


            sent_msg_obj = await save_message(session, thread.id, "user", content_to_db)
            
            inputs = {"messages": [HumanMessage(content=content_to_ai)]}
            

        config = {"configurable": {"thread_id": thread.id}}
        
        final_state = await graph.ainvoke(inputs, config)

        get_new_state = await graph.aget_state(config)

        last_msg = get_new_state.values["messages"][-1]

        assistant_msg_id = None
        assistant_msg_created_at = None

        if isinstance(last_msg, AIMessage) and last_msg.content:
            async with AsyncSessionLocal() as session:
                assistant_msg_obj = await save_message(session, thread.id, "assistant", last_msg.content)
                assistant_msg_id = assistant_msg_obj.id
                assistant_msg_created_at = assistant_msg_obj.created_at


        return {
            "thread_id": thread.id,
            "user_message_id": sent_msg_obj.id,
            "user_created_at": sent_msg_obj.created_at,
            "assistant_message_id": assistant_msg_id,
            "assistant_created_at": assistant_msg_created_at,
            "response": last_msg.content,
            "status": "success",
        }

@app.route('/threads', methods=['GET'])
async def list_threads():
    # data = await request.get_json()
    # user_id = data.get("user_id")
    user_id = request.args.get("user_id")

    async with AsyncSessionLocal() as session:
        threads = await get_user_threads(session, user_id)
        threads_json = [
            {
                "id": t.id, 
                "title": t.title, 
                "created_at": t.created_at.isoformat()
            } for t in threads
        ]

        return jsonify(threads_json)

@app.route('/threads/create', methods=['POST'])
async def create_thread():
    data = await request.get_json()
    user_id = data.get("user_id")

    thread_id = "new_thread"

    if not user_id:
        return jsonify({"error": "User ID is required."}), 400

    async with AsyncSessionLocal() as session:
        thread = await get_or_create_thread(session, user_id, thread_id)
        
        return jsonify({
            "status": "success",
            "thread_id": thread.id,
            "user_id": thread.user_id,
            "title": thread.title,
            "created_at": thread.created_at.isoformat() if thread.created_at else None
        }), 201

@app.route('/threads/<thread_id>/title', methods=['PATCH'])
async def rename_thread(thread_id):
    data = await request.get_json()
    user_id = data.get("user_id")
    new_title = data.get("title")

    if not user_id or not new_title:
        return jsonify({"error": "User ID and title are required"}), 400

    async with AsyncSessionLocal() as session:
        updated_thread = await update_thread_title(session, user_id, thread_id, new_title)
        
        if updated_thread:
            return jsonify({
                "status": "success",
                "thread_id": updated_thread.id,
                "new_title": updated_thread.title
            }), 200
        else:
            return jsonify({"error": "Thread not found or unauthorized"}), 404

@app.route('/threads/<thread_id>', methods=['DELETE'])
async def delete_thread(thread_id):
    data = await request.get_json()
    user_id = data.get("user_id")

    if not user_id:
        return jsonify({"error": "User ID is required"}), 400
    
    async with AsyncSessionLocal() as session:
        success = await remove_thread(session, user_id, thread_id)
        
        if success:
            return jsonify({
                "status": "success",
                "message": f"Thread {thread_id} and all its messages have been deleted."
            }), 200
        
        else:
            return jsonify({"error": "Thread not found or unauthorized"}), 404

@app.route('/threads/<thread_id>/messages', methods=['GET'])
async def list_messages(thread_id):
    # data = await request.get_json()
    # user_id = data.get("user_id")
    user_id = request.args.get("user_id")
    
    if not user_id:
        return jsonify({"error:" "User ID is required."}), 400

    async with AsyncSessionLocal() as session:
        messages_query = (
            select(Message)
            .join(Thread, Message.thread_id == Thread.id)
            .where(Message.thread_id == thread_id, Thread.user_id == user_id)
            .order_by(Message.created_at.asc())
        )

        result = await session.execute(messages_query)

        if not result:
            return jsonify({"error": "Access denied or thread do not exist."}), 403

        messages = result.scalars().all()

        messages_json = [
            {
                "id": m.id,
                "role": m.role,
                "content": m.content,
                "created_at": m.created_at.isoformat()
            } for m in messages
        ]

        return jsonify(messages_json)
