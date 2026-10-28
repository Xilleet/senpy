from __future__ import annotations

import contextlib
import ctypes
import os


def _is_russian_os() -> bool:
    """Определяет, русский ли интерфейс у ОС пользователя."""
    if "ru" in os.environ.get("LANG", "").lower():
        return True
    if os.name == "nt":
        with contextlib.suppress(AttributeError, OSError):
            return ctypes.windll.kernel32.GetUserDefaultUILanguage() == 1049
    return False


IS_RU = _is_russian_os()

TSUNDERE_FLAVORS = {
    "RPY001": "(╯°□°)╯︵ ┻━┻ «Ты посмел вставить табуляцию вместо пробелов?! Ren'Py такое не прощает, ленивый бака!»"
    if IS_RU
    else "(╯°□°)╯︵ ┻━┻ «Tabs instead of spaces in indentation?! Ren'Py does not forgive this, lazy baka!»",
    "RPY002": "(｀ε´ ) «Ты копировал текст прямо из Word?! Эти фигурные кавычки сломают весь код, бака!»"
    if IS_RU
    else "(｀ε´ ) «Did you paste from Word?! Smart quotes break Python code, baka!»",
    "RPY101": "(¬_¬ ) «Бака! Ты используешь переменную в диалоге, но даже не объявил её! О чем ты вообще думал?!»"
    if IS_RU
    else "(¬_¬ ) «B-Baka! You used a variable in dialogue without declaring it! What were you thinking?!»",
    "RPY102": "(╬ Ò﹏Ó) «Ты делаешь += к переменной, которой НЕТ! Это же чистый NameError при запуске, идиот!»"
    if IS_RU
    else "(╬ Ò﹏Ó) «You're doing += to a variable that DOESN'T EXIST! That's a guaranteed NameError, idiot!»",
    "RPY103": "( ﾟдﾟ) «Ты вставил в условие if переменную из воздуха! Игра вылетит, бестолочь!»"
    if IS_RU
    else "( ﾟдﾟ) «You put a phantom variable in an if-condition! The game will crash, dummy!»",
    "RPY104": "(>_< ) «Создал переменную на лету без default?! Сохранения у игроков сломаются после патча, дурак!»"
    if IS_RU
    else "(>_< ) «Created a variable on the fly without a default?! You'll break player save files on the next patch, fool!»",
    "RPY105": "(╬ Ò﹏Ó) «Ты меняешь переменную из define?! define — это КОНСТАНТА! Для меняющихся переменных есть default, идиот!»"
    if IS_RU
    else "(╬ Ò﹏Ó) «You mutated a variable from define?! define is for CONSTANTS! Use default for mutable state, idiot!»",
    "RPY106": "(╬ Ò﹏Ó) «Ты импортировал стандартный random?! Откат назад и сохранения развалятся на куски, бестолочь! Используй renpy.random!»"
    if IS_RU
    else "(╬ Ò﹏Ó) «You imported standard random?! Rollback and save files will fall apart, dummy! Use renpy.random!»",
    "RPY107": "(눈_눈) «Ты используешь замшелую функцию из каменного века Ren'Py! Обнови код на современный аналог, дед!»"
    if IS_RU
    else "(눈_눈) «Using an obsolete Ren'Py function from the stone age! Update your code to modern APIs, boomer!»",
    "RPY108": "(╬ Ò﹏Ó) «Ты объявил переменную одного типа, а пихаешь в неё совсем другой?! Числа со строками не складываются, идиот!»"
    if IS_RU
    else "(╬ Ò﹏Ó) «You declared one type and assigned a completely incompatible one?! Types don't mix like that, dummy!»",
    "RPY109": "(；￣Д￣) «Ты вызываешь функцию в init python раньше, чем загрузился файл с ней! Ren'Py грузит файлы по алфавиту, слепой!»"
    if IS_RU
    else "(；￣Д￣) «Calling a function in init python before its file even loaded?! Ren'Py loads alphabetically, blind idiot!»",
    "RPY201": "(╯°□°)╯︵ ┻━┻ «Ты меняешь переменную ПРЯМО ВНУТРИ ЭКРАНА?! Экраны так не работают, тупица!»"
    if IS_RU
    else "(╯°□°)╯︵ ┻━┻ «Mutating variables DIRECTLY INSIDE A SCREEN?! Screens don't work like that, dummy!»",
    "RPY202": "(눈_눈) «Экран читает переменную без default! В главном меню игра сразу рухнет, гений!»"
    if IS_RU
    else "(눈_눈) «A screen is reading a variable without a default! It's going to crash right in the main menu, genius!»",
    "RPY203": "(눈_눈) «Кнопка без действия action?! И на что игрок нажимать будет, на пустоту?!»"
    if IS_RU
    else "(눈_눈) «A button without an action?! What is the player supposed to click on, thin air?!»",
    "RPY204": "( ﾟдﾟ) «Экран, который ты вызываешь, вообще не существует! Куда ты собрался переключать игрока, идиот?!»"
    if IS_RU
    else "( ﾟдﾟ) «The screen you are calling does not exist! Where are you trying to switch the player to, dummy?!»",
    "RPY205": "(╯°□°)╯︵ ┻━┻ «Ты впихнул Python-цикл for/while прямо в экран?! UI будет лагать как не в себя, дурак!»"
    if IS_RU
    else "(╯°□°)╯︵ ┻━┻ «A Python for/while loop inside a screen?! The UI is going to lag horribly, fool!»",
    "RPY206": "(╬ Ò﹏Ó) «Ты вызвал функцию в action со скобками?! Она сработает ещё до клика, прямо при открытии экрана, идиот!»"
    if IS_RU
    else "(╬ Ò﹏Ó) «Calling a function directly in action?! It executes during screen render, not on click! Use Function(), dummy!»",
    "RPY207": "(；￣Д￣) «Ты передал не те параметры в use screen или call screen! Скрипт упадёт с ошибкой, бестолочь!»"
    if IS_RU
    else "(；￣Д￣) «Invalid parameters in screen call or use statement! It will crash with an Exception, dummy!»",
    "RPY208": "(╬ Ò﹏Ó) «Ты используешь SetVariable на локальной переменной экрана?! Это же утечка в глобальный store, бестолочь! Используй SetScreenVariable!»"
    if IS_RU
    else "(╬ Ò﹏Ó) «Using SetVariable on a screen-local variable?! That leaks into the global store instead of updating the screen, dummy! Use SetScreenVariable!»",
    "RPY301": "(；￣Д￣) «Открыл тег и забыл закрыть?! Весь дальнейший текст игры поплывет, глаза б мои тебя не видели!»"
    if IS_RU
    else "(；￣Д￣) «Opened a text tag and forgot to close it?! The whole game's text is going to bleed, I can't even look at it!»",
    "RPY302": "( ﾟдﾟ) «Прыжок на метку, которой ВООБЩЕ НЕТ?! Куда ты собрался прыгать, в пустоту?!»"
    if IS_RU
    else "( ﾟдﾟ) «Jumping to a label that DOES NOT EXIST?! Where are you jumping to, the void?!»",
    "RPY303": "(￣︿￣) «Не вижу прямых переходов на метку... Надеюсь, ты вызываешь её через динамический роутер, а не просто забросил!»"
    if IS_RU
    else "(￣︿￣) «No static references to this label... I hope you're calling it dynamically, and didn't just abandon it!»",
    "RPY304": "(｀ε´ ) «Что это за цвет такой?! Ты даже в hex-кодах умудрился опечататься!»"
    if IS_RU
    else "(｀ε´ ) «What kind of color is that?! You even managed to make a typo in hex codes!»",
    "RPY305": '(｀ε´ ) «Ты забыл экранировать кавычки внутри реплики! Поставь слэш \\", иначе игра просто упадет!»'
    if IS_RU
    else '(｀ε´ ) «Unescaped quotes inside dialogue! Escape them with \\", otherwise the game crashes!»',
    "RPY306": "(；￣Д￣) «Ты сделал call на метку, но пути к return не видно! Убедись, что сюжет не утечёт в чужие сцены!»"
    if IS_RU
    else "(；￣Д￣) «You called a label, but no clear return path was found! Make sure control flow doesn't bleed out!»",
    "RPY307": "(╬ Ò﹏Ó) «Эта метка уже была объявлена раньше! Игра упадёт на старте из-за дубликата, слепой!»"
    if IS_RU
    else "(╬ Ò﹏Ó) «Duplicate label declaration! The game will crash on startup, blind idiot!»",
    "RPY308": "(；￣Д￣) «Сюжет в этой метке никуда не уходит и просто провалится в следующую сцену! Поставь return или jump, бестолочь!»"
    if IS_RU
    else "(；￣Д￣) «This label doesn't end with jump or return, it falls right through into the next scene, dummy!»",
    "RPY309": "(￣︿￣) «Целая группа сцен зациклена сама в себе и отрезана от start! И кто в это играть будет, призраки?!»"
    if IS_RU
    else "(￣︿￣) «This whole group of scenes loops into itself and is unreachable from start! Who's going to play this, ghosts?!»",
    "RPY310": "(╬ Ò﹏Ó) «Ты вызываешь метку call не с теми аргументами! Это же фатальный TypeError во время игры, идиот!»"
    if IS_RU
    else "(╬ Ò﹏Ó) «You called a label with invalid arguments! That's a fatal TypeError during gameplay, idiot!»",
    "RPY401": "(눈_눈) «В одном пункте меню ты переменную дал, а во втором забыл?! Выберут второй — и игра крашнется!»"
    if IS_RU
    else "(눈_눈) «You defined a variable in one menu choice but forgot it in another?! They pick the second one and it crashes!»",
    "RPY402": "(；￣Д￣) «Ты создал пункт в меню, но внутри пусто?! Сюжет просто провалится вниз, бестолочь!»"
    if IS_RU
    else "(；￣Д￣) «You made a menu choice but left it completely empty?! The story will just fall through, dummy!»",
    "RPY403": "(￣︿￣) «Условие всегда False! Этот кусок сюжета вообще НИКОГДА не выполнится, гений!»"
    if IS_RU
    else "(￣︿￣) «Condition is always False! This branch will NEVER execute, genius!»",
    "RPY404": "(>_< ) «Ты читаешь переменную, которая существует только в одной развилке! Игрок пойдёт другой дорогой — и всё рухнет!»"
    if IS_RU
    else "(>_< ) «You're reading a variable that only exists in one branch! If the player takes the other path, it all crashes!»",
    "RPY501": "(￣︿￣) «Музыка не найдена! В этой сцене будет гробовая тишина, глупый!»"
    if IS_RU
    else "(￣︿￣) «Music file not found! There will be dead silence in this scene, stupid!»",
    "RPY502": "(￣︿￣) «Спрайт или фон не найден! Персонаж растворится в воздухе прямо посреди сцены, слепой!»"
    if IS_RU
    else "(￣︿￣) «Sprite or background not found! The character will vanish into thin air, blind dummy!»",
    "RPY503": "(눈_눈) «Этот файл ассета нигде не используется! Зря только место на диске жрёт, бака!»"
    if IS_RU
    else "(눈_눈) «Unused media asset found! It's just wasting disk space and build size, baka!»",
    "RPY504": "(눈_눈) «Эта картинка переопределяет или дублирует ранее объявленную! Надеюсь, ты сделал это намеренно, бака!»"
    if IS_RU
    else "(눈_눈) «This image overrides or duplicates an earlier declaration! I hope that was intentional, genius!»",
    "RPY505": "(눈_눈) «Ты пустил звук по незарегистрированному каналу или зациклил voice! Уши игрокам сломать хочешь, бака?!»"
    if IS_RU
    else "(눈_눈) «Playing audio on an unregistered channel or looping voice! Trying to break the player's ears, baka?!»",
    "RPY601": "(╬ Ò﹏Ó) «Ты сломал переменную в переводе! Оригинал ждёт [var], а у тебя опечатка! Игра вылетит с KeyError, идиот!»"
    if IS_RU
    else "(╬ Ò﹏Ó) «Variable mismatch in translation! The original expects [var], but you made a typo! The game will crash with KeyError, dummy!»",
    "RPY602": "(；￣Д￣) «Теги форматирования в переводе не совпадают с оригиналом! Текст игры поплывёт, бестолочь!»"
    if IS_RU
    else "(；￣Д￣) «Formatting tags in translation don't match the original! Text styling will break, idiot!»",
    "RPY603": "(￣︿￣) «Ты оставил строку перевода пустой! У игроков там будет пустота вместо текста!»"
    if IS_RU
    else "(￣︿￣) «You left the translation string empty! Players will see blank air instead of text!»",
    "RPY701": "(︶︿︶) «Эта константа нигде не используется! Зачем ты её объявил?»"
    if IS_RU
    else "(︶︿︶) «This constant is never used! Why did you declare it, baka?»",
    "RPY702": "(︶︿︶) «Этот трансформ нигде не используется! Мёртвый код — это грязно!»"
    if IS_RU
    else "(︶︿︶) «This transform is never used! Dead code is dirty, baka!»",
    "RPY703": "(︶︿︶) «Этот экран нигде не вызывается! Зачем ты его написал?»"
    if IS_RU
    else "(︶︿︶) «This screen is never called! Why did you write it, baka?»",
    "RPY100": "(╯°□°)╯︵ ┻━┻ «Этот файл вообще не в UTF-8! Он молча выпал из проверки — ищи кракозябры в игре, бака!»"
    if IS_RU
    else "(╯°□°)╯︵ ┻━┻ «This file isn't even UTF-8! It silently dropped out of the check — enjoy the mojibake in-game, baka!»",
}

TSUNDERE_UI = {
    "intro": "П-подумаешь! Сканирую твою директорию: {path}... Н-не то чтобы мне был интересен твой сценарий, бака!"
    if IS_RU
    else "H-Hmph! Scanning your directory: {path}... I-It's not like I'm interested in your script, baka!",
    "clean_title": "Н-не то чтобы мне нравился твой сценарий... но сюжетных дыр и крашей я не нашла, бака!"
    if IS_RU
    else "I-It's not like I like your script... but I didn't find any plot holes or crashes, baka!",
    "clean_sub": "Проверено {lines:,} строк за {elapsed:.3f}с. Д-доволен?!"
    if IS_RU
    else "Checked {lines:,} lines in {elapsed:.3f}s. A-Are you happy now?!",
    "summary": "Твои позорные ошибки" if IS_RU else "Your shameful mistakes",
    "fixed": "Я... я закрыла за тобой {count} открытых ошибок! Н-но не думай, что ты мне нравишься, идиот!"
    if IS_RU
    else "I... I closed {count} open tags for you! B-But don't think I like you or anything, idiot!",
    "fixable": "Там есть {count} ошибок, которые я могла бы починить за тебя через --fix... если вежливо попросишь, бака!"
    if IS_RU
    else "There are {count} tags I could fix for you with --fix... if you ask nicely, baka!",
    "errors": "Найдено {summary_str}! Иди и исправляй, я не буду играть в такую сломанную новеллу! ({elapsed:.3f}s)"
    if IS_RU
    else "Found {summary_str}! Go fix them, I'm not playing such a broken novel! ({elapsed:.3f}s)",
    "warnings": "Найдено {summary_str}... Жить можно, но я за тобой слежу, бака! ({elapsed:.3f}s)"
    if IS_RU
    else "Found {summary_str}... It's playable, but I'm watching you, baka! ({elapsed:.3f}s)",
    "defaults_generated": "Я... я сгенерировала за тебя файл {path} с {count} переменными! Т-только не думай, что мне не всё равно на твои сохранения, бака!"
    if IS_RU
    else "I... I generated {path} with {count} variables for you! D-Don't think I care about your save files, baka!",
    "info_omitted": "Я заметила ещё {count} мелких нюансов, но не покажу их, пока не попросишь через --info, бака!"
    if IS_RU
    else "I noticed {count} minor things, but I won't show them unless you ask with --info, baka!",
    "coverage": "(¬_¬ ) «Вот твои проценты перевода! Не бросай новеллу недопереведённой, бака!»"
    if IS_RU
    else "(¬_¬ ) «Here's your translation progress! Don't leave your visual novel half-translated, baka!»",
    "stats": "(//∇//) «Я... я пересчитала все твои словечки ({words:,} слов)! Целых {hours:.1f} ч. чтения! И не думай, что я буду читать всё это!»"
    if IS_RU
    else "(//∇//) «I... I counted all your dialogue ({words:,} words)! That's ~{hours:.1f} hrs of reading! Don't think I'm going to read all of it!»",
    "init_ci": "(//∇//) «Я... я создала для тебя {path}! Только закоммить его в Git, и не заставляй меня проверять твои пуллреквесты вручную, бака!»"
    if IS_RU
    else "(//∇//) «I... I created {path} for you! Just commit it to Git, and don't make me review your pull requests by hand, baka!»",
    "export_wiki": "(//∇//) «Я... я сгенерировала диздок твоего сценария в {path}! Изучай свои переменные и не смей их путать, бака!»"
    if IS_RU
    else "(//∇//) «I... I generated documentation for your visual novel in {path}! Study your variables and don't mess them up, baka!»",
    "graph": "(//∇//) «Я... я нарисовала карту твоих переходов в {path}! Н-но не думай, что мне интересно, куда пойдёт твой герой, бака!»"
    if IS_RU
    else "(//∇//) «I... I drew a story map in {path}! B-But don't think I care where your protagonist goes, baka!»",
    "generate_stubs": "Я сгенерировала заглушки типов в {path} с {count} переменными! Теперь твой Pylance не посмеет подчеркивать код красным, бака!"
    if IS_RU
    else "I generated type stubs in {path} with {count} variables! Now your Pylance won't dare to underline your code in red, baka!",
}
