#!/usr/bin/env bash
# stream-report.sh - document everything about an RTSP stream and test it for packet loss.
#
# Usage:   ./stream-report.sh <rtsp-url> [loss-test-seconds]
# Example: ./stream-report.sh rtsp://12.28.64.216:5000/0_0 60
#
# Needs ffmpeg + ffprobe (macOS: brew install ffmpeg | Ubuntu: apt install ffmpeg).
# Writes everything into ./stream-report-<timestamp>/ and prints report.txt at the end.
#
# Each section below is one standalone command you can copy and run by hand -
# replace "$URL" with the stream address and "$OUT/..." with any filename.

set -u
URL="${1:?usage: $0 <rtsp-url> [loss-test-seconds]}"
LOSS_SECS="${2:-60}"
SAMPLE_SECS=12
OUT="stream-report-$(date +%Y%m%d-%H%M%S)"
mkdir -p "$OUT"
R="$OUT/report.txt"

section() { printf '\n==================== %s ====================\n' "$1" | tee -a "$R"; }
say()     { echo "$*" | tee -a "$R"; }

say "Stream report for $URL"
say "Generated $(date) on $(hostname)"

# ---------------------------------------------------------------------------
# 1. What's in the stream - codec, resolution, frame rate, color, audio format.
#    -rtsp_transport tcp : ask for RTP inside the RTSP TCP connection, so loss can't skew the probe
#    -show_streams       : every property ffprobe knows about each stream (video + audio)
# ---------------------------------------------------------------------------
section "1. Stream properties"
ffprobe -v error -rtsp_transport tcp -show_streams "$URL" > "$OUT/streams-full.txt" 2>&1
# The fields worth documenting, pulled out of the full dump:
grep -E '^(index|codec_type|codec_name|profile|level|width|height|pix_fmt|field_order|color_space|color_transfer|color_primaries|r_frame_rate|avg_frame_rate|has_b_frames|sample_rate|channels|channel_layout|bit_rate)=' \
  "$OUT/streams-full.txt" | tee -a "$R"
say "(full dump: $OUT/streams-full.txt)"
say "Note: level is level x 30 for HEVC (150 = 5.0) and level x 10 for H.264 (40 = 4.0)."
say "Note: has_b_frames is the decoder's reserved reorder depth, NOT proof of B-frames - see section 3."

# ---------------------------------------------------------------------------
# 2. Record a short sample to a file, so the frame-level checks below run on
#    identical data instead of re-pulling the live stream each time.
#    -c copy   : no re-encoding - the file holds exactly the bytes the encoder sent
#    -f mpegts : MPEG transport stream, the normal broadcast container
# ---------------------------------------------------------------------------
section "2. Recording ${SAMPLE_SECS}s sample"
ffmpeg -hide_banner -loglevel error -rtsp_transport tcp -i "$URL" -t "$SAMPLE_SECS" -c copy -f mpegts "$OUT/sample.ts"
say "saved $OUT/sample.ts ($(du -h "$OUT/sample.ts" | cut -f1))"

# ---------------------------------------------------------------------------
# 3. GOP structure - the frame type of every frame (I = full picture, P = changes
#    from the previous frame, B = references future frames too).
#    -show_entries frame=key_frame,pkt_size,pict_type : one CSV row per frame
#    Columns come out in ffprobe's own order: key_frame, size in bytes, type.
# ---------------------------------------------------------------------------
section "3. GOP structure"
ffprobe -v error -select_streams v -show_entries frame=key_frame,pkt_size,pict_type -of csv=p=0 \
  "$OUT/sample.ts" > "$OUT/frames.csv"
FPS=$(ffprobe -v error -select_streams v -show_entries stream=avg_frame_rate -of default=nw=1:nk=1 "$OUT/sample.ts" | head -1 | awk -F/ '{printf "%.3f", $1/$2}')
say "First 240 frames (60 per row):"
awk -F, 'NR<=240{printf "%s", $3}' "$OUT/frames.csv" | fold -w 60 | tee -a "$R"; say ""
say "Frame counts and average size by type:"
awk -F, '{s[$3]+=$2; n[$3]++} END{for (t in n) printf "  %s-frames: %4d   avg %7.1f KB\n", t, n[t], s[t]/n[t]/1024}' "$OUT/frames.csv" | tee -a "$R"
awk -F, -v fps="$FPS" '$1==1{if(last)gap=NR-last; last=NR} END{if(gap) printf "Keyframe every %d frames = %.2f s at %s fps\n", gap, gap/fps, fps; else print "Only one keyframe in the sample - GOP is longer than the sample."}' \
  "$OUT/frames.csv" | tee -a "$R"

# Reordering check - the real test for B-frames.
#   pts = when a frame is displayed, dts = when it is decoded.
#   B-frames make pts jump backwards; a constant pts-dts gap with no backwards jumps
#   just means the encoder reserved a reorder slot it never uses.
ffprobe -v error -select_streams v -show_entries packet=pts,dts -of csv=p=0 "$OUT/sample.ts" > "$OUT/timestamps.csv"
awk -F, 'NR>1 && $1<prev{back++} {gap[$1-$2]++; prev=$1}
  END{printf "Display order goes backwards: %d times (%s)\n", back+0, back ? "B-frames / reordering present" : "no B-frames";
      for (g in gap) printf "  pts-dts offset %s ticks on %d frames\n", g, gap[g]}' "$OUT/timestamps.csv" | tee -a "$R"

# ---------------------------------------------------------------------------
# 4. Actual bitrates - add up the bytes of every packet and divide by the duration.
#    (The bit_rate field in section 1 is often N/A for live video; this is the measured value.)
#    ffprobe prints pts_time before size regardless of the order you ask for them.
# ---------------------------------------------------------------------------
section "4. Measured bitrates"
for s in v a; do
  ffprobe -v error -select_streams "$s" -show_entries packet=size,pts_time -of csv=p=0 "$OUT/sample.ts" |
    awk -F, -v s="$s" 'NR==1{t0=$1} {b+=$2; t=$1} END{if (t>t0) printf "  %s: %.0f kbps (over %.1f s)\n", (s=="v"?"video":"audio"), b*8/(t-t0)/1000, t-t0}'
done | tee -a "$R"

# ---------------------------------------------------------------------------
# 5. Packet-loss test - decode the stream over UDP and TCP at the same time.
#    UDP is what VLC uses by default and shows real network loss; TCP retransmits,
#    so it's the clean baseline. Running both at once means both see the same network.
#    -f null -     : decode every frame and throw it away - we only want the error log
#    -buffer_size  : big UDP receive buffer so the receiving host isn't the one dropping
#                    (Linux caps it at net.core.rmem_max unless you raise that)
# ---------------------------------------------------------------------------
section "5. Packet loss test (${LOSS_SECS}s, UDP and TCP in parallel)"
ffmpeg -hide_banner -nostats -rtsp_transport udp -buffer_size 8M -i "$URL" -t "$LOSS_SECS" -map 0:v -f null - > "$OUT/udp.log" 2>&1 &
UDP_PID=$!
ffmpeg -hide_banner -nostats -rtsp_transport tcp -i "$URL" -t "$LOSS_SECS" -map 0:v -f null - > "$OUT/tcp.log" 2>&1 &
TCP_PID=$!
# If no UDP packets arrive (e.g. a firewall drops them), ffmpeg can sit there forever -
# stop it once the TCP run is done plus a grace period.
wait "$TCP_PID"
sleep 10
if kill -0 "$UDP_PID" 2>/dev/null; then
  kill -INT "$UDP_PID" 2>/dev/null; wait "$UDP_PID" 2>/dev/null
  say "UDP run did not finish on its own - no RTP/UDP arrived (likely firewall/NAT, not loss)."
fi
wait "$UDP_PID" 2>/dev/null
EXPECTED=$(awk -v f="$FPS" -v s="$LOSS_SECS" 'BEGIN{printf "%d", f*s}')
for t in udp tcp; do
  L="$OUT/$t.log"
  say "$(echo "$t" | tr a-z A-Z):"
  say "  packet-loss events (RTP: missed): $(grep -c 'RTP: missed' "$L")"
  say "  packets lost in total:            $(grep -o 'missed [0-9]*' "$L" | awk '{n+=$2} END{print n+0}')"
  say "  undecodable frames:               $(grep -cE 'Could not find ref|concealing|error while decoding' "$L")  (a burst at startup is normal - up to one GOP)"
  say "  frames decoded:                   $(grep -o 'frame= *[0-9]*' "$L" | tail -1 | grep -o '[0-9]*' || echo 0) of ~$EXPECTED expected"
done

section "How to read this"
say "- UDP losses but clean TCP: packets are being lost on the network path - not an encoder fault."
say "- Both runs show decode errors past startup: the stream itself is corrupt (look at the encoder)."
say "- UDP decodes 0 frames: RTP/UDP never arrived - usually a firewall/NAT dropping it (FortiGate:"
say "  the rtsp session-helper only watches TCP 554 by default)."
say ""
say "Files: $OUT/  (report.txt, streams-full.txt, sample.ts, frames.csv, timestamps.csv, udp.log, tcp.log)"
