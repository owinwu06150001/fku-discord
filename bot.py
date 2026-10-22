import os
import threading
import traceback
import discord
from discord import app_commands
from flask import Flask
import imageio_ffmpeg

FFMPEG_PATH = imageio_ffmpeg.get_ffmpeg_exe()

app = Flask(__name__)


@app.route("/")
def home():
  return "Voice Bot with Error Logging is running!"


def run_flask():
  port = int(os.environ.get("PORT", 10000))
  app.run(host="0.0.0.0", port=port)


class MyBot(discord.Client):

  def __init__(self):
    intents = discord.Intents.default()
    intents.voice_states = True
    super().__init__(intents=intents)
    self.tree = app_commands.CommandTree(self)
    self.target_channel_id = None  # 語音頻道 ID
    self.error_channel_id = None  # 報錯文字頻道 ID

  async def setup_hook(self):
    await self.tree.sync()
    print("指令已成功同步")

  # 輔助方法：發送錯誤訊息到指定的報錯頻道
  async def send_error_log(self, guild: discord.Guild, error_msg: str):
    print(f"[錯誤記錄] {error_msg}")
    if self.error_channel_id:
      channel = self.get_channel(self.error_channel_id)
      if channel:
        try:
          await channel.send(
              f"**[機器人報錯]**\n伺服器: {guild.name if guild else '未知'}\n```python\n{error_msg[:1900]}\n```"
          )
        except Exception as e:
          print(f"無法發送報錯訊息到頻道: {e}")


client = MyBot()

def play_continuous_silence(voice_client, guild=None):
  if voice_client and voice_client.is_connected():
    source = discord.FFmpegPCMAudio(
        "anullsrc=r=48000:cl=stereo",
        before_options="-f lavfi",
        options="-vn",
        executable=FFMPEG_PATH,
    )

    def after_playing(error):
      if error:
        err_str = f"播放無聲時發生錯誤: {error}"
        client.loop.create_task(client.send_error_log(guild, err_str))

      if voice_client.is_connected():
        play_continuous_silence(voice_client, guild)

    if not voice_client.is_playing():
      voice_client.play(source, after=after_playing)


@client.event
async def on_ready():
  print(f"語音機器人已成功登入：{client.user}")

  if client.target_channel_id:
    channel = client.get_channel(client.target_channel_id)
    if channel:
      try:
        voice_client = await channel.connect()
        play_continuous_silence(voice_client, channel.guild)
        print(f"已重新加入語音頻道：{channel.name}")
      except Exception as e:
        err_msg = (
            f"啟動自動重連失敗:\n{traceback.format_exc()}"
        )
        await client.send_error_log(None, err_msg)


@client.event
async def on_voice_state_update(member, before, after):
  if member.id == client.user.id:
    if before.channel is not None and after.channel is None:
      if client.target_channel_id:
        print("偵測到機器人斷線 嘗試在 5 秒後重新連線")
        import asyncio

        await asyncio.sleep(5)
        channel = client.get_channel(client.target_channel_id)
        if channel:
          try:
            voice_client = await channel.connect()
            play_continuous_silence(voice_client, channel.guild)
            print("已重新連線回語音頻道。")
          except Exception as e:
            err_msg = f"斷線後重連失敗:\n{traceback.format_exc()}"
            await client.send_error_log(channel.guild, err_msg)


@client.tree.command(name="加入", description="讓機器人加入目前的語音頻道")
async def join(interaction: discord.Interaction):
  if not interaction.user.voice or not interaction.user.voice.channel:
    await interaction.response.send_message(
        "請先加入一個語音頻道", ephemeral=True
    )
    return

  channel = interaction.user.voice.channel
  client.target_channel_id = channel.id

  try:
    if interaction.guild.voice_client is not None:
      await interaction.guild.voice_client.move_to(channel)
      voice_client = interaction.guild.voice_client
    else:
      voice_client = await channel.connect()

    play_continuous_silence(voice_client, interaction.guild)

    await interaction.response.send_message(
        f"已加入語音頻道：**{channel.name}**"
    )
  except Exception as e:
    err_msg = f"執行 /加入語音 時發生錯誤:\n{traceback.format_exc()}"
    await client.send_error_log(interaction.guild, err_msg)
    await interaction.response.send_message(
        "加入語音頻道時發生未預期的錯誤 已回報", ephemeral=True
    )


@client.tree.command(name="離開", description="讓機器人離開目前的語音頻道")
async def leave(interaction: discord.Interaction):
  client.target_channel_id = None
  voice_client = interaction.guild.voice_client

  if voice_client and voice_client.is_connected():
    await voice_client.disconnect()
    await interaction.response.send_message("已離開語音頻道")
  else:
    await interaction.response.send_message(
        "機器人目前不在任何語音頻道中", ephemeral=True
    )

@client.tree.command(name="設定報錯頻道", description="將當前文字頻道設定為機器人的錯誤回報頻道")
@app_commands.checks.has_permissions(administrator=True)
async def set_error_channel(interaction: discord.Interaction):
  client.error_channel_id = interaction.channel.id
  await interaction.response.send_message(
      f"設定成功 (**{interaction.channel.name}**)。",
      ephemeral=True,
  )



@set_error_channel.error
async def set_error_channel_error(
    interaction: discord.Interaction, error: app_commands.AppCommandError
):
  if isinstance(error, app_commands.MissingPermissions):
    await interaction.response.send_message(
        "你沒有權限使用此指令", ephemeral=True
    )
  else:
    await interaction.response.send_message(
        f"發生未預期的錯誤: {error}", ephemeral=True
    )


if __name__ == "__main__":
  flask_thread = threading.Thread(target=run_flask)
  flask_thread.start()

  TOKEN = os.environ.get("DISCORD_TOKEN")
  if TOKEN:
    client.run(TOKEN)
  else:
    print("找不到 DISCORD_TOKEN 環境變數")
