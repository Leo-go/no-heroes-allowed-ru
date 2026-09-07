# No Heroes Allowed! — русификация (PSP)

Любительская локализация **No Heroes Allowed!** (USA, `NPUG80460`) на базе дампа kohryu.

Репозиторий: https://github.com/Leo-go/no-heroes-allowed-ru  
Рабочий ISO: `B:\psp games\No Heroes Allowed RUS\NHA_USA_RUS.iso` (в git **не** кладём).  
Оригинал: `B:\psp games\[PSP] No Heroes Allowed! [USA]_up_by_kohryu.iso` — **не патчится**.

## Статус

| Область | Состояние |
|--------|-----------|
| Меню / пауза / опции (`GameText.bin`) | RU латиницей (bitmap-шрифт без глифов А–Я) |
| Загрузка, кирки, стадии, монстры, SYS | RU латиницей |
| Брифинги Бэдмена (`filelist.fbe` SPT) | RU латиницей |
| Туториал (`script.fbe`) + квесты filelist | RU латиницей |
| Реплики героев в данже (`HeroTextData`) | RU латиницей |
| Данж на день (`MainichiText`) | RU латиницей |
| Автосейв / ошибки карты памяти | Настоящая кириллица (другой шрифт) |
| Бестиарий (`zukan/Ency.pack`) | RU латиницей (имена/статы + описания) |
| Названия навыков (`SkillName.fbe`) | Картинки GIM, ENG |
| EBOOT/BOOT | **Не трогать** |

Диалоговый и титульный шрифт — один bitmap-атлас. Кириллица в нём рисуется латинскими двойниками (`ч`→`4`). Поэтому в эти экраны кладётся **читаемый транслит**, не UTF-8 А–Я. Перепаковка пикселей атласа даёт чёрный экран.

## Сборка

Нужны Python 3.10+, `pip install pycdlib pillow`, распакованный ISO в `iso_extracted\` (локально, не в git).

```
python tools/build_stage1.py
```

Пишет `NHA_USA_RUS.iso` **тем же размером**, что retail (in-place патч содержимого файлов, каталог ISO не трогается) — так надёжнее для реальной PSP. Если файл открыт в PPSSPP — будет `NHA_USA_RUS_new.iso`.

На Memory Stick клади именно этот ISO (старые пересобранные/с другим размером лучше убрать). Запуск: Reset / Boot, не savestate.

Проверка образа: `python tools/verify_psp_iso.py`

```
B:\psp games\tools\PPSSPP\PPSSPPWindows64.exe "B:\psp games\No Heroes Allowed RUS\NHA_USA_RUS.iso"
```

## Структура

```
tools/          сборка, шрифт, MYU0/FBE/SPT
translation/    исходники RU (ui.py, *.tsv)
originals/      бэкапы файлов из ISO (gitignore)
iso_extracted/  распакованный UMD (gitignore)
```

## Дисклеймер

Это фанатский патч. ISO и дамп игры в репозиторий не входят. Нужна своя копия USA-образа.
