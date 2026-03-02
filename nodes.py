import os
from dotenv import load_dotenv
from typing import List

from state import AgentState
from llm_provider import call_llm
from prompt import SYSTEM_PROMPT

from langgraph.prebuilt import ToolNode
from langchain_core.tools import tool
from langchain_core.messages import AIMessage, SystemMessage
from langgraph.graph import END


# LLM
load_dotenv()
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
MODEL="gpt-4o-mini"

# NODE
async def chatbot(state: AgentState):
    llm = call_llm()

    system_message = SystemMessage(content=SYSTEM_PROMPT)

    message = [system_message] + state["messages"]
    
    response = await llm.ainvoke(message)

    return {"messages": [response]}

# ROUTER
def should_continue(state: AgentState): 
    messages = state["messages"]
    last_message = messages[-1]

    if isinstance(last_message, AIMessage) and last_message.tool_calls:
        return "tools"
    
    return END

# TOOLS
@tool 
def suggest_image(search_arg: str): 
    """
        Suggest an image to the user based on a single visual concept.

        Use this tool ONLY when the user explicitly asks to see, view, or receive an image suggestion.
        The input must be a short, concrete visual keyword (one concept only), such as an object,
        place, person, or scene.

        This tool does NOT perform image search. It selects a random image from an internal image
        library that matches the provided keyword.

        Do NOT use this tool for abstract concepts, explanations, comparisons, or when the user
        is not requesting an image.
    """
    return {
            "required_action": {
                "function": {
                    "name": "suggest_image",
                    "arguments": {
                        "search": search_arg
                    }
                },
            }
        }

@tool
def favorite_image(idimage_arg: str):
    """
        Mark an image as a user favorite.

        Use this tool ONLY when the user explicitly requests to favorite, save, or mark an image
        as favorite. The user must clearly reference an image that has already been shown or
        suggested, and the provided argument must be the exact image ID.

        Do NOT infer user intent. Do NOT call this tool automatically after suggesting or
        displaying an image. Do NOT use this tool without an explicit user action.
    """

    return {
            "required_action": {
                "function": {
                    "name": "favorite_image",
                    "arguments": {
                        "idimage": idimage_arg
                    }
                },
            }
        }

@tool
def save_draft(idimages_arg: List[str], content_arg: str, date_arg: str, time_arg: str):
    """
        Save a post as a draft.
        
        This tool does NOT publish or schedule posts.

        Use this tool ONLY when the user explicitly asks to create or save a draft post.
        This tool represents the FINAL action of the draft creation flow.

        All images must already be selected and provided as image IDs.
        Do NOT suggest, search, or generate images when using this tool.
        Do NOT call image suggestion tools as part of this action.

        The date and time must reflect the user's local timezone at the moment the draft
        was requested and must follow these formats:
        - Date: YYYY-MM-DD
        - Time: HH:mm (24-hour format)

    """

    return {
            "required_action": {
                "function": {
                    "name": "save_draft",
                    "arguments": {
                        "idimages": idimages_arg,
                        "content": content_arg,
                        "date": date_arg,
                        "time": time_arg
                    }
                },
            }
        }

@tool
def publish_post(idimages_arg: List[str], content_arg: str, date_arg: str, time_arg: str):
    """
        Publish or schedule post to the user's social media accounts at a specific date and time.

        Use this tool ONLY when the user explicitly confirms that they want to publish or schedule a post.
        This tool represents a FINAL and potentially irreversible action.

        All images must already be selected and provided as valid image IDs.
        Do NOT suggest, search, or generate images.
        Do NOT modify the post content.
        Do NOT call any other tools as part of this action.

        This tool is NOT for saving drafts.

        The date and time must reflect the user's local timezone at the moment of confirmation
        and must follow these formats:
        - Date: YYYY-MM-DD
        - Time: HH:mm (24-hour format)
    """

    return {
            "required_action": {
                "function": {
                    "name": "publish_post",
                    "arguments": {
                        "idimages": idimages_arg,
                        "content": content_arg,
                        "date": date_arg,
                        "time": time_arg
                    }
                },
            }
        }

@tool
def edit_post(iddraft_arg: str, idimages_arg: str, content_arg: str, date_arg: str, time_arg: str, preserve_current_post_arg: str):
    """
        Edit an existing scheduled post.

        Use this tool ONLY when the user explicitly asks to edit or modify an existing post
        that has already been created or scheduled. This tool updates content, images, or
        scheduling details without publishing the post.

        This tool does NOT publish posts.

        If preserveCurrentPostContent is true:
        - The current images or media must be kept
        - The idimages argument MUST be omitted or empty

        If preserveCurrentPostContent is false:
        - idimages must contain the full list of image IDs to associate with the post

        Do NOT suggest, search, or generate images.
        Do NOT infer missing data.
        Do NOT call image suggestion tools.

        The date and time must reflect the user's local timezone at the moment of the edit
        and must follow these formats:
        - Date: YYYY-MM-DD
        - Time: HH:mm (24-hour format)
    """
    
    return {
            "required_action": {
                "function": {
                    "name": "edit_post",
                    "arguments": {
                        "iddraft": iddraft_arg,
                        "idimage": idimages_arg,
                        "content": content_arg,
                        "date": date_arg,
                        "time": time_arg,
                        "preserveCurrentPostContent": preserve_current_post_arg
                    }
                },
            }
        }

@tool
def cancel_post(iddraft_arg: str,):
    """
        Cancel a previously scheduled post.

        Use this tool ONLY when the user explicitly requests to cancel or remove a scheduled post.
        This action stops the post from being published and represents a FINAL decision.

        This tool does NOT edit, publish, or save posts.
        It only cancels an existing scheduled post identified by its draft ID.

        Do NOT infer user intent.
        Do NOT call any other tools as part of this action.
    """

    return {
            "required_action": {
                "function": {
                    "name": "cancel_post",
                    "arguments": {
                        "iddraft": iddraft_arg,
                    }
                },
            }
        }

@tool
def list_scheduled_posts():
    """
        List all posts that are currently scheduled for future publication.

        Use this tool ONLY when the user explicitly asks to view, list, or see their scheduled posts.
        This tool is read-only and does not create, edit, publish, or cancel posts.

        Do NOT call this tool as part of publishing, editing, or canceling workflows
        unless the user explicitly requests to see the list.
    """

    return {
            "required_action": {
                "function": {
                    "name": "list_scheduled_posts",
                    "arguments": {}
                },
            }
        }

@tool
def list_posted_posts():
    """
        List all social media posts that have already been published.

        Use this tool ONLY when the user explicitly asks to view, list, or review past posts.
        This tool is read-only and returns historical data only.

        Published posts cannot be edited, canceled, or rescheduled.
        Do NOT call this tool as part of scheduling, editing, or publishing workflows
        unless the user explicitly requests to see posted content.
    """

    return {
            "required_action": {
                "function": {
                    "name": "list_posted_posts",
                    "arguments": {}
                },
            }
        }

@tool
def add_image_to_post_creator(idimages_arg: str):
    """
        Add one or more images to the Post Creator interface for preview and editing.

        Use this tool ONLY to update the Post Creator UI state.
        This tool is temporary and does NOT save, publish, schedule, or edit any post.

        The provided image IDs must already exist and are only added for user preview
        and manual editing inside the Post Creator.

        Do NOT call this tool to persist data.
        Do NOT call this tool as a replacement for save, edit, or publish actions.
    """

    return {
            "required_action": {
                "function": {
                    "name": "add_image_to_post_creator",
                    "arguments": {
                        "idimages": idimages_arg,
                    }
                },
            }
        }
    
@tool
def add_caption_to_post_creator(caption_arg):
    """
        Add a caption to the Post Creator interface for preview and manual editing.

        Use this tool ONLY to update the Post Creator UI state.
        This tool is temporary and does NOT save, schedule, publish, or edit any post.

        The caption is added for user preview and can be freely modified before
        any save or publish action.

        Do NOT call this tool to persist content.
        Do NOT treat this tool as a final action.
    """

    return {
            "required_action": {
                "function": {
                    "name": "add_caption_to_post_creator",
                    "arguments": {
                        "caption": caption_arg,
                    }
                },
            }
        }

@tool
def get_post_creator_content():
    """
        Retrieve the current content from the Post Creator interface.

        This tool returns the temporary UI state, including selected images and caption.
        It is read-only and does NOT save, validate, publish, or schedule any post.

        Use this tool ONLY to display or review the current Post Creator content
        at the user's request.

        Do NOT treat the returned data as confirmed or final content.
    """

    return {
            "required_action": {
                "function": {
                    "name": "get_post_creator_content",
                    "arguments": {}
                },
            }
        }

@tool
def get_user_datetime():
    """
        Retrieve the current date and time based on the user's timezone.

        This tool is a utility used to obtain the user's current local date and time
        when needed for scheduling, drafts, or time-sensitive operations.

        This tool is read-only and does NOT confirm user intent.
        Do NOT treat the returned date and time as approval to save, edit, publish,
        or cancel any post.

        Use this tool ONLY when the current user-local date or time is explicitly
        required to complete another requested action.
    """

    return {
            "required_action": {
                "function": {
                    "name": "get_user_datetime",
                    "arguments": {}
                },
            }
        }

@tool 
def suggest_reel(search_arg: str): 
    """
        Suggest an reel to the user based on a single visual concept.

        Use this tool ONLY when the user explicitly asks to see, view, or receive an image suggestion.
        The input must be a short, concrete visual keyword (one concept only), such as an object,
        place, person, or scene.

        This tool does NOT perform image search. It selects a random image from an internal image
        library that matches the provided keyword.

        Do NOT use this tool for abstract concepts, explanations, comparisons, or when the user
        is not requesting an image.
    """
    return {
            "required_action": {
                "function": {
                    "name": "suggest_reel",
                    "arguments": {
                        "search": search_arg
                    }
                },
            }
        }

@tool 
def suggest_carousel(search_arg: str): 
    """
        Suggest an carousel to the user based on a single visual concept.

        Use this tool ONLY when the user explicitly asks to see, view, or receive an image suggestion.
        The input must be a short, concrete visual keyword (one concept only), such as an object,
        place, person, or scene.

        This tool does NOT perform image search. It selects a random image from an internal image
        library that matches the provided keyword.

        Do NOT use this tool for abstract concepts, explanations, comparisons, or when the user
        is not requesting an image.
    """
    return {
            "required_action": {
                "function": {
                    "name": "suggest_carousel",
                    "arguments": {
                        "search": search_arg
                    }
                },
            }
        }

TOOLS = [suggest_image, favorite_image, save_draft, publish_post, edit_post, cancel_post, list_scheduled_posts, list_posted_posts, add_image_to_post_creator, add_caption_to_post_creator, get_post_creator_content, get_user_datetime, suggest_reel, suggest_carousel]
TOOL_NODE = ToolNode(TOOLS)