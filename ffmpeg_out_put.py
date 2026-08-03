import subprocess
import json

# 定义前景、背景视频和音乐的路径
fg_video_path = 'media/videos/cs_radar_chart/1080p60/PlayerRadarChart.mov'
# bgm_path = 'music/Piano Fantasia - Song for Denise (Maxi version).mp3'
bgm_path = 'music/Michael Jackson - Thriller.mp3'
# bg_video_path = 'bg/vecteezy_abstract-plexus-tech-background-with-glowing-blue-shiny_21050150~1.mp4'
# bg_video_path = 'bg/chakra.mp4'
# bg_video_path = 'bg/stringss.mp4'
bg_video_path = 'bg/halloween_shadows_in_window.mp4'


# 调用 ffprobe 获取视频时长
def get_video_duration(video_path):
    result = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "json", video_path],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True
    )
    info = json.loads(result.stdout)
    return float(info['format']['duration'])

# 调用 ffprobe 获取视频分辨率
def get_video_resolution(video_path):
    result = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "stream=width,height", "-of", "json", video_path],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True
    )
    info = json.loads(result.stdout)
    width = int(info['streams'][0]['width'])
    height = int(info['streams'][0]['height'])
    return width, height

# 获取前景视频的时长
foreground_duration = get_video_duration(fg_video_path)

# 获取前景视频的分辨率
fg_width, fg_height = get_video_resolution(fg_video_path)

# 背景视频循环播放并与前景视频叠加，使用 NVENC GPU 加速，同时缩放背景至前景视频大小，指定颜色空间为 yuv420p
# 添加亮度和对比度调整
brightness = -0.05
contrast = 1.0
subprocess.run([
    'ffmpeg', '-hwaccel', 'cuda', '-stream_loop', '-1', '-t', str(foreground_duration), '-i', bg_video_path,
    '-i', fg_video_path,
    '-filter_complex', f'[0:v]scale={fg_width}:{fg_height},eq=brightness={brightness}:contrast={contrast}[bg];[bg]format=yuv420p[bgfmt];[bgfmt][1:v]overlay',
    '-c:v', 'h264_nvenc', '-shortest', 'temp_output_video.mp4'
])

# 背景音乐循环播放并与生成的视频合成，继续使用 NVENC
subprocess.run([
    'ffmpeg', '-i', 'temp_output_video.mp4', '-stream_loop', '-1', '-t', str(foreground_duration), '-i', bgm_path,
    '-c:v', 'copy', '-c:a', 'aac', '-shortest', 'final_output_video_with_music.mp4'
])
