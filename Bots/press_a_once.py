"""Нажимает A один раз в текущем окне игры. Запускай на нужной реплике диалога."""


def run(bot):
    bot.log("Нажимаю игровую кнопку A один раз.")
    result = bot.press("A", frames=2, release_frames=1)
    bot.log(f"Готово: кадры {result['start_frame']} → {result['end_frame']}.")
