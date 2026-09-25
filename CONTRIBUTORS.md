# Contributors

GitHub's own contributors list only counts commits, so it misses the people who
changed what this firmware does without pushing any. This file is for them.

| | |
|---|---|
| **Akil0515** ([Telegram](https://t.me/Akil0515)) | Suggested routing the least significant bits of each transmit sample — the four the 12-bit DAC discards — straight to the GPIO output pins. That became [sample-locked GPIO outputs](docs/tx-gpio-bitmap.md): four header pins whose every edge belongs to one specific transmitted sample, at a fixed offset from its RF, for nothing. |
| **matsvandamme** ([GitHub](https://github.com/matsvandamme)) | The reverse engineering, the patches, the build system, the measurements and the course. |

If you suggested something here and are not on this list, that is an oversight
rather than a judgement — open an issue and it gets fixed.
