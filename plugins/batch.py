from pyrogram import Client, filters
from pyrogram.types import Message
import re
import asyncio
import config
import random  # Importing random module
from app import LOGGER
from utils.telegram_logger import send_info, send_error, send_warning
from plugins.video_message import message_queue, worker_task, process_video_queue
from asyncio import create_task

TELEGRAM_LINK_PATTERN = r"https://t\.me/(?:c/)?([^/]+)/(\d+)"

@Client.on_message(filters.command("batch") & filters.user(config.SUDO_USERS))
async def batch_process(client: Client, message: Message):
    """
    Process multiple videos between start and end message links.
    Usage: /batch https://t.me/c/123456789/123 https://t.me/c/123456789/456
    """
    try:
        if len(message.command) < 3:
            await message.reply_text(
                "⚠️ Please provide both start and end Telegram message links.\n"
                "Example: `/batch https://t.me/c/123456789/123 https://t.me/c/123456789/456`"
            )
            return

        global worker_task
        if worker_task is None or worker_task.done():
            LOGGER.info("Starting video processing worker for batch operation")
            worker_task = create_task(process_video_queue(False))

        start_link = message.command[1]
        end_link = message.command[2]

        start_match = re.match(TELEGRAM_LINK_PATTERN, start_link)
        if not start_match:
            await message.reply_text(
                "⚠️ Invalid start link format.\n"
                "Example: `https://t.me/c/123456789/123`"
            )
            return

        start_chat_identifier, start_msg_id = start_match.groups()
        start_msg_id = int(start_msg_id)

        if start_chat_identifier.isdigit():
            chat_id = int(f"-100{start_chat_identifier}")
        else:
            chat_id = start_chat_identifier

        end_match = re.match(TELEGRAM_LINK_PATTERN, end_link)
        if not end_match:
            await message.reply_text(
                "⚠️ Invalid end link format.\n" "Example: `https://t.me/c/123456789/456`"
            )
            return

        end_chat_identifier, end_msg_id = end_match.groups()
        end_msg_id = int(end_msg_id)

        if end_chat_identifier.isdigit():
            end_chat_id = int(f"-100{end_chat_identifier}")
        else:
            end_chat_id = end_chat_identifier

        if str(chat_id) != str(end_chat_id):
            await message.reply_text("⚠️ Both links must be from the same chat!")
            return

        if end_msg_id < start_msg_id:
            start_msg_id, end_msg_id = end_msg_id, start_msg_id

        total_messages = end_msg_id - start_msg_id + 1

        status_message = await message.reply_text(
            f"🔄 Processing {total_messages} messages from ID {start_msg_id} to {end_msg_id}"
        )
        await send_info(
            client,
            f"Starting batch processing of {total_messages} messages from chat {chat_id}",
        )

        videos_queued = 0
        queue_size_before = message_queue.qsize()

        current_msg_id = start_msg_id

        while current_msg_id <= end_msg_id:
            try:
                msg = await client.get_messages(chat_id, current_msg_id)

                if msg and (msg.video or msg.document or msg.animation):
                    videos_queued += 1
                    await message_queue.put((client, msg))

                    if videos_queued % 10 == 0:
                        current_queue_size = message_queue.qsize()
                        await status_message.edit_text(
                            f"🔄 Batch processing: {videos_queued} media files queued out of {current_msg_id - start_msg_id + 1} messages checked\n"
                            f"Current queue size: {current_queue_size}"
                        )

                # Sleep for a random time between 30-60 seconds after processing each message
                await asyncio.sleep(random.randint(30, 60))  # Sleep 30 to 60 seconds

                if current_msg_id % 20 == 0:
                    await asyncio.sleep(1)

            except Exception as e:
                if (
                    "MESSAGE_NOT_FOUND" in str(e)
                    or "message not found" in str(e).lower()
                ):
                    pass
                elif "FLOOD_WAIT" in str(e) or "flood wait" in str(e).lower():
                    wait_time = (
                        int(str(e).split(" ")[-1])
                        if str(e).split(" ")[-1].isdigit()
                        else 5
                    )
                    await status_message.edit_text(
                        f"⏳ Rate limited. Waiting for {wait_time} seconds..."
                    )
                    await asyncio.sleep(wait_time)
                    continue
                else:
                    LOGGER.error(f"Error processing message {current_msg_id}: {str(e)}")
                    await send_warning(
                        client,
                        f"Error in batch processing for message {current_msg_id}: {str(e)}",
                    )

            current_msg_id += 1

            if current_msg_id % 50 == 0:
                progress = ((current_msg_id - start_msg_id) / total_messages) * 100
                current_queue_size = message_queue.qsize()
                await status_message.edit_text(
                    f"🔄 Progress: {progress:.1f}%\n"
                    f"• Checked: {current_msg_id - start_msg_id}/{total_messages} messages\n"
                    f"• Media queued: {videos_queued} files\n"
                    f"• Queue size: {current_queue_size}"
                )

        final_queue_size = message_queue.qsize()
        queue_change = final_queue_size - queue_size_before

        await status_message.edit_text(
            f"✅ Batch processing completed!\n"
            f"• Checked {total_messages} messages\n"
            f"• Queued {videos_queued} media files for processing\n"
            f"• Current queue size: {final_queue_size} (+{queue_change})\n\n"
            f"🔄 Items in queue are now being processed automatically."
        )

        await send_info(
            client,
            f"Completed batch processing: {videos_queued} media files queued from {total_messages} messages. Queue size: {final_queue_size}",
        )

    except Exception as e:
        LOGGER.error(f"Batch processing error: {str(e)}")
        await send_error(client, "Batch processing failed", e)
        await message.reply_text(
            f"❌ An error occurred during batch processing: {str(e)}"
        )
