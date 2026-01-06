
        "🛠 <b>Сборки предметов и способностей</b>\n\n"
        "Выберите категорию или найдите героя:",
        reply_markup=keyboard.as_markup(),
        parse_mode="HTML"
    )

@dp.callback_query(F.data == "builds_search")
async def search_hero(callback: types.CallbackQuery, state: FSMContext):
    await callback.message.answer(
        "🔍 <b>Поиск героя</b>\n\n"
        "Введите имя героя (например: Pudge, Invoker, Crystal Maiden):",
        parse_mode="HTML"
    )
    await state.set_state(ProfileStates.searching_hero)
    await callback.answer()

@dp.message(ProfileStates.searching_hero)
async def process_hero_search(message: types.Message, state: FSMContext):
    search_term = message.text.strip().lower()
    
    with open('hero_names.json', 'r', encoding='utf-8') as f:
        heroes = json.load(f)
    
    found_heroes = []
    for hero_id, hero_name in heroes.items():
        if search_term in hero_name.lower():
            found_heroes.append((int(hero_id), hero_name))
    
    if found_heroes:
        keyboard = InlineKeyboardBuilder()
        for hero_id, hero_name in found_heroes[:10]:
            keyboard.button(text=hero_name, callback_data=f"hero_build_{hero_id}")
        keyboard.button(text="⬅️ Назад", callback_data="builds_back")
        keyboard.adjust(1)
        
        await message.answer(
            f"🔍 <b>Найдено героев:</b> {len(found_heroes)}\n\n"
            f"Выберите героя:",
            reply_markup=keyboard.as_markup(),
            parse_mode="HTML"
        )
    else:
        await message.answer(
            "❌ Герой не найден. Попробуйте другое имя или используйте категории.",
            reply_markup=get_main_keyboard()
        )
    
    await state.clear()

@dp.callback_query(F.data.startswith("builds_"))
async def builds_by_role(callback: types.CallbackQuery):
    role_id = callback.data.split("_")[1]
    
    if role_id == "search":
        await search_hero(callback, FSMContext)
        return
    
    # Загружаем данные из hero_builds.json
    try:
        with open('hero_builds.json', 'r', encoding='utf-8') as f:
            heroes_builds = json.load(f)
    except FileNotFoundError:
        await callback.message.answer("❌ Файл сборок не найден.")
        return
    
    role_names = {
        "carry": "Керри",
        "mid": "Мидер",
        "offlane": "Оффлейнер",
        "support": "Саппорт",
        "hard_support": "Хард саппорт"
    }
    
    role_name = role_names.get(role_id, role_id)
    
    # Ищем героев с этой ролью
    heroes = []
    for hero_id, hero_data in heroes_builds.items():
        if role_name in hero_data.get('primary_roles', []) or role_name in hero_data.get('secondary_roles', []):
            heroes.append((int(hero_id), hero_data.get('name', f"Герой {hero_id}")))
    
    if not heroes:
        await callback.answer("❌ Нет героев для этой роли")
        return
    
    keyboard = InlineKeyboardBuilder()
    for hero_id, hero_name in heroes:
        keyboard.button(text=hero_name, callback_data=f"hero_build_{hero_id}")
    
    keyboard.button(text="⬅️ Назад", callback_data="builds_back")
    keyboard.adjust(1)
    
    await callback.message.edit_text(
        f"🛠 <b>Герои ({role_name}):</b>\n\n"
        f"Выберите героя для просмотра сборки:",
        reply_markup=keyboard.as_markup(),
        parse_mode="HTML"
    )
    await callback.answer()

    @dp.callback_query(F.data.startswith("hero_build_"))
async def hero_build_display(callback: types.CallbackQuery):
    hero_id = callback.data.split("_")[2]
    
    # Загружаем данные из hero_builds.json
    try:
        with open('hero_builds.json', 'r', encoding='utf-8') as f:
            heroes_builds = json.load(f)
    except FileNotFoundError:
        await callback.message.answer("❌ Файл сборок не найден.")
        await callback.answer()
        return
    
    hero_data = heroes_builds.get(hero_id)
    
    if not hero_data:
        await callback.message.answer(f"❌ Сборки для героя с ID {hero_id} не найдены.")
        await callback.answer()
        return
    
    hero_name = hero_data.get('name', f"Герой {hero_id}")
    
    # Получаем первую роль из списка
    roles = hero_data.get('primary_roles', [])
    if not roles:
        roles = hero_data.get('secondary_roles', [])
    
    if not roles:
        await callback.message.answer(f"❌ Для героя {hero_name} не указаны роли.")
        await callback.answer()
        return
    
    role = roles[0]
    builds = hero_data.get('builds', {})
    
    if role not in builds:
        # Пытаемся найти любую сборку
        if builds:
            role = list(builds.keys())[0]
        else:
            await callback.message.answer(f"❌ Для героя {hero_name} нет сборок.")
            await callback.answer()
            return
    
    build = builds[role]
    
    response = f"""
🛠 <b>{hero_name} ({role})</b>

🎒 <b>Предметы:</b>
"""
    
    for item in build.get("items", []):
        response += f"• {item}\n"
    
    response += f"""
⚡ <b>Способности:</b>
{build.get('skills', 'Не указано')}

📈 <b>Прокачка:</b>
{build.get('skill_build', 'Не указано')}

🌟 <b>Таланты:</b>
{build.get('talents', 'Не указано')}

🎮 <b>Стиль игры:</b>
{build.get('playstyle', 'Не указано')}

<i>Сборка основана на текущей мете</i>
"""
    
    # Кнопки для других ролей если есть
    keyboard = InlineKeyboardBuilder()
    other_roles = [r for r in builds.keys() if r != role]
    for other_role in other_roles:
        keyboard.button(text=f"🎯 {other_role}", callback_data=f"hero_role_{hero_id}_{other_role}")
    
    keyboard.button(text="⬅️ Назад", callback_data="builds_back")
    keyboard.adjust(2)
    
    await callback.message.edit_text(
        response,
        reply_markup=keyboard.as_markup(),
        parse_mode="HTML"
    )
    await callback.answer()


@dp.callback_query(F.data.startswith("hero_role_"))
async def hero_role_switch(callback: types.CallbackQuery):
    parts = callback.data.split("_")
    hero_id = parts[2]
    role = parts[3]
    
    # Загружаем данные из hero_builds.json
    try:
        with open('hero_builds.json', 'r', encoding='utf-8') as f:
            heroes_builds = json.load(f)
    except FileNotFoundError:
        await callback.message.answer("❌ Файл сборок не найден.")
        return
    
    hero_data = heroes_builds.get(hero_id)
    if not hero_data:
        await callback.message.answer("❌ Герой не найден.")
        return
    
    hero_name = hero_data.get('name', f"Герой {hero_id}")
    builds = hero_data.get('builds', {})
    
    if role not in builds:
        await callback.message.answer(f"❌ Для героя {hero_name} нет сборки для роли {role}.")
        return
    
    build = builds[role]
    
    response = f"""
🛠 <b>{hero_name} ({role})</b>

🎒 <b>Предметы:</b>
"""
    
    for item in build.get("items", []):
        response += f"• {item}\n"
    
    response += f"""
⚡ <b>Способности:</b>
{build.get('skills', 'Не указано')}

📈 <b>Прокачка:</b>
{build.get('skill_build', 'Не указано')}

🌟 <b>Таланты:</b>
{build.get('talents', 'Не указано')}

🎮 <b>Стиль игры:</b>
{build.get('playstyle', 'Не указано')}

<i>Сборка основана на текущей мете</i>
"""
    
    keyboard = InlineKeyboardBuilder()
    other_roles = [r for r in builds.keys() if r != role]
    for other_role in other_roles:
        keyboard.button(text=f"🎯 {other_role}", callback_data=f"hero_role_{hero_id}_{other_role}")
    
    keyboard.button(text="⬅️ Назад", callback_data=f"hero_build_{hero_id}")
    keyboard.adjust(2)
    
    await callback.message.edit_text(
        response,
        reply_markup=keyboard.as_markup(),
        parse_mode="HTML"
    )
    await callback.answer()
    
@dp.callback_query(F.data == "builds_back")
async def builds_back(callback: types.CallbackQuery):
    await builds_menu(callback.message)
    await callback.answer()

# ========== SUPPORT ==========
@dp.message(F.text == "❤️ Поддержка")
async def support_cmd(message: types.Message):
    keyboard = InlineKeyboardBuilder()
    keyboard.button(text="💸 Донат", url="https://www.donationalerts.com/r/shindaqwe")
    keyboard.button(text="🛠 Тех поддержка", url="https://t.me/DotaShindaHelper_bot")
    keyboard.adjust(1)
    
    await message.answer(
        "❤️ <b>Поддержка проекта</b>\n\n"
        "Если вам нравится бот, вы можете поддержать его развитие!\n\n"
        "💸 <b>Донат</b> - финансовая поддержка\n"
        "🛠 <b>Тех поддержка</b> - помощь с ботом",
        reply_markup=keyboard.as_markup(),
        parse_mode="HTML"
    )

# ========== BACK BUTTONS ==========
@dp.callback_query(F.data == "profile_back")
async def profile_back(callback: types.CallbackQuery):
    await profile_cmd(callback.message)
    await callback.answer()

@dp.callback_query(F.data == "refresh_profile")
async def refresh_profile(callback: types.CallbackQuery):
    await callback.answer("🔄 Обновляю...")
    await profile_cmd(callback.message)

@dp.callback_query(F.data == "detailed_stats")
async def detailed_stats(callback: types.CallbackQuery):
    user = get_user(callback.from_user.id)
    if not user or not user[2]:
        await callback.answer("❌ Сначала привяжите профиль!")
        return
    
    account_id = user[2]
    await callback.answer("⏳ Получаю подробную статистику...")
    
    winloss = await get_winloss(account_id)
    matches = await get_matches(account_id, 50)
    
    if not winloss:
        await callback.message.answer("❌ Не удалось получить данные.")
        return
    
    total_wins = winloss.get('win', 0)
    total_losses = winloss.get('lose', 0)
    total_matches = total_wins + total_losses
    
    if matches:
        recent_stats = {'kills': 0, 'deaths': 0, 'assists': 0, 'wins': 0}
        
        for match in matches:
            recent_stats['kills'] += match.get('kills', 0)
            recent_stats['deaths'] += match.get('deaths', 0)
            recent_stats['assists'] += match.get('assists', 0)
            
            is_radiant = match.get('player_slot', 0) < 128
            radiant_win = match.get('radiant_win', False)
            if (is_radiant and radiant_win) or (not is_radiant and not radiant_win):
                recent_stats['wins'] += 1
        
        avg_kills = recent_stats['kills'] / len(matches)
        avg_deaths = recent_stats['deaths'] / len(matches)
        avg_assists = recent_stats['assists'] / len(matches)
        recent_winrate = (recent_stats['wins'] / len(matches) * 100)
        
        kda = (avg_kills + avg_assists) / avg_deaths if avg_deaths > 0 else avg_kills + avg_assists
    else:
        avg_kills = avg_deaths = avg_assists = kda = 0
        recent_winrate = 0
    
    response = f"""
📊 <b>Подробная статистика</b>
