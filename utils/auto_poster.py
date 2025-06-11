from pyrogram.types import Message
from pyrogram import Client
from config import POST_CHAT

async def auto_poster(client: Client, message: Message, content: dict, media_type: str):
    """
    Automatically post the updates to the specified chat after processing.
    """

    try:
        
        release_year = content['release_date'][:4] if content['release_date'] else ""
        
        caption_text = f"""
`{content['title']}` `({release_year})` `{f"Season {content['season'][0]['season_number']}" if media_type == "show" else ""} {f"Episode {content['season'][0]['episodes'][0]['episode_number']}" if media_type == "show" else ""}`
**Quality :** `{content['season'][0]["episodes"][0]["quality"][0]["type"] if media_type == "show" else content["quality"][0]["type"]}`
**Size :** `{content['season'][0]["episodes"][0]["quality"][0]["size"] if media_type == "show" else content["quality"][0]["size"]}`

**Genres :** `{', '.join(content["genres"])}`
**Score ⭐️:** `{content['vote_average']}` ~ `{content['vote_count']} votes`
**{"Creator" if media_type == "show" else "Director"} 📽:** `{",".join(content['creators']) if media_type == "show" else ",".join(content['directors']) }`
**Stars 👥:** `{",".join([actor['name'] for actor in content['cast'][:4]])}`

**Story Line :** {content['overview']}

    """
        await client.send_photo(
            chat_id=POST_CHAT,
            photo=f"https://image.tmdb.org/t/p/w500{content['poster_path']}",
            caption=caption_text
        )

    except Exception as e:
        print(f"Error in auto_poster: {e}")
        