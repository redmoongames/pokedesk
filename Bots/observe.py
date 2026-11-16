"""Без нажатий: 60 игровых секунд выводит координаты, деньги, уровень и HP."""


def run(bot):
    bot.log("Наблюдение за текущей игрой. Никакие кнопки не нажимаются.")
    for _ in range(60):
        state = bot.state()
        party = state["party"]
        mon = party[0] if party else None
        bot.log(f"Кадр {state['frame']} · {state['position']} · деньги {state['money']} · "
                + (f"{mon['nickname']} Lv {mon['level']}, HP {mon['hp']}/{mon['max_hp']}" if mon else "команда пока пуста"))
        bot.wait_frames(60)
    bot.log("Наблюдение завершено.")
