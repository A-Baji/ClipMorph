def generate_srt(segments, srt_path):

    def format_time(seconds):
        ms = int((seconds - int(seconds)) * 1000)
        h, m, s = int(seconds // 3600), int(
            (seconds % 3600) // 60), int(seconds % 60)
        return f"{h:02}:{m:02}:{s:02},{ms:03}"

    with open(srt_path, 'w', encoding='utf-8') as f:
        idx = 1
        for seg in segments:
            f.write(f"{idx}\n")
            f.write(
                f"{format_time(seg['start'])} --> {format_time(seg['end'])}\n")
            f.write(f"{seg['text']}\n\n")
            idx += 1
