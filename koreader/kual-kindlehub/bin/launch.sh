#!/bin/sh
# One tap from KUAL: start KOReader and open the current Kindle Hub screen.
# The flag tells the Kindle Hub plugin it was started from here (see its "Open when KOReader starts").
mkdir -p /mnt/us/koreader/settings
touch /mnt/us/koreader/settings/kindlehub.launch
exec /mnt/us/koreader/koreader.sh --kual
