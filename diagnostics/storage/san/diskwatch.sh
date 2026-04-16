#!/bin/bash

INTERVAL=${1:-2}
FILTER="^(md[0-9]|dm-[0-9]+|nvme[0-9])"

# ANSI colors
CYAN="\033[1;36m"
GREEN="\033[1;32m"
YELLOW="\033[1;33m"
RED="\033[1;31m"
RESET="\033[0m"
BOLD="\033[1m"

read_diskstats() {
    declare -gA DS_READ DS_WRITE DS_IO_MS DS_RIOS DS_WIOS DS_RTIME DS_WTIME
    while read -r _ _ dev r_ios _ r_sec r_time w_ios _ w_sec w_time _ io_ms _; do
        if [[ "$dev" =~ $FILTER ]]; then
            DS_READ[$dev]=$r_sec
            DS_WRITE[$dev]=$w_sec
            DS_IO_MS[$dev]=$io_ms
            DS_RIOS[$dev]=$r_ios
            DS_WIOS[$dev]=$w_ios
            DS_RTIME[$dev]=$r_time
            DS_WTIME[$dev]=$w_time
        fi
    done < /proc/diskstats
}

declare -A PREV_READ PREV_WRITE PREV_IO_MS PREV_RIOS PREV_WIOS PREV_RTIME PREV_WTIME
read_diskstats
for dev in "${!DS_READ[@]}"; do
    PREV_READ[$dev]=${DS_READ[$dev]}
    PREV_WRITE[$dev]=${DS_WRITE[$dev]}
    PREV_IO_MS[$dev]=${DS_IO_MS[$dev]}
    PREV_RIOS[$dev]=${DS_RIOS[$dev]}
    PREV_WIOS[$dev]=${DS_WIOS[$dev]}
    PREV_RTIME[$dev]=${DS_RTIME[$dev]}
    PREV_WTIME[$dev]=${DS_WTIME[$dev]}
done

sleep "$INTERVAL"

while true; do
    read_diskstats

    clear
    printf "${CYAN}${BOLD}%-20s %10s %10s %10s %8s${RESET}\n" \
        "DEVICE" "READ MB/s" "WRITE MB/s" "AWAIT ms" "%UTIL"
    printf "${CYAN}%-20s %10s %10s %10s %8s${RESET}\n" \
        "--------------------" "----------" "----------" "----------" "--------"

    for dev in $(echo "${!DS_READ[@]}" | tr ' ' '\n' | sort); do
        dr=$(( DS_READ[$dev]   - ${PREV_READ[$dev]:-0} ))
        dw=$(( DS_WRITE[$dev]  - ${PREV_WRITE[$dev]:-0} ))
        dm=$(( DS_IO_MS[$dev]  - ${PREV_IO_MS[$dev]:-0} ))
        dri=$(( DS_RIOS[$dev]  - ${PREV_RIOS[$dev]:-0} ))
        dwi=$(( DS_WIOS[$dev]  - ${PREV_WIOS[$dev]:-0} ))
        drt=$(( DS_RTIME[$dev] - ${PREV_RTIME[$dev]:-0} ))
        dwt=$(( DS_WTIME[$dev] - ${PREV_WTIME[$dev]:-0} ))

        read_mb=$(awk "BEGIN {printf \"%.1f\", $dr * 512 / 1048576 / $INTERVAL}")
        write_mb=$(awk "BEGIN {printf \"%.1f\", $dw * 512 / 1048576 / $INTERVAL}")
        util=$(awk "BEGIN {u=$dm / ($INTERVAL * 1000) * 100; if(u>100)u=100; printf \"%.1f\", u}")
        await=$(awk "BEGIN {total=$dri+$dwi; if(total>0) printf \"%.1f\", ($drt+$dwt)/total; else print \"0.0\"}")

        util_int=${util%.*}
        if   (( util_int >= 85 )); then uc=$RED
        elif (( util_int >= 60 )); then uc=$YELLOW
        else uc=$GREEN
        fi

        await_int=${await%.*}
        if   (( await_int >= 50 )); then ac=$RED
        elif (( await_int >= 20 )); then ac=$YELLOW
        else ac=$GREEN
        fi

        printf "%-20s %10s %10s ${ac}%10s${RESET} ${uc}%8s%%${RESET}\n" \
            "$dev" "$read_mb" "$write_mb" "$await" "$util"

        PREV_READ[$dev]=${DS_READ[$dev]}
        PREV_WRITE[$dev]=${DS_WRITE[$dev]}
        PREV_IO_MS[$dev]=${DS_IO_MS[$dev]}
        PREV_RIOS[$dev]=${DS_RIOS[$dev]}
        PREV_WIOS[$dev]=${DS_WIOS[$dev]}
        PREV_RTIME[$dev]=${DS_RTIME[$dev]}
        PREV_WTIME[$dev]=${DS_WTIME[$dev]}
    done

    printf "\n${BOLD}Refreshing every ${INTERVAL}s — Ctrl+C to exit${RESET}\n"
    sleep "$INTERVAL"
    read_diskstats
done
