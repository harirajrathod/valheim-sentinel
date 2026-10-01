"""
monitor/roasts.py - Comedic Norse Roasts & Session Context Engine
Contains 150+ battle-tested comedic messages and session-linked callbacks.
"""

import random
import re
from typing import Dict, Any, Optional, List

from core.config import SafeFormatDict

JOIN_TEMPLATES = [
    "⚔️ **{name}** dropped into the realm! Watch out for falling timber!",
    "🌲 **{name}** has joined. Hide your trees before they crush your longhouse!",
    "🐝 **{name}** joined the server. The bees are... mildly concerned.",
    "🍯 **{name}** has arrived to inspect if the bees are happy!",
    "🦟 **{name}** logged in. Somewhere in the Plains, a Deathsquito just smiled.",
    "🍖 **{name}** spawned with 25 HP and an empty belly. Someone cook sausages!",
    "🍻 **{name}** kicked the tavern doors open demanding tasty mead!",
    "🐗 **{name}** has entered the realm. Reminder: Boar loves you.",
    "⚡ The Valkyrie dropped **{name}** face-first onto the sacrificial altar.",
    "👁️ Odin peered through the clouds, sighed, and muttered: 'Oh great, **{name}** is back.'",
    "🪓 **{name}** logged in to chop trees and accidentally destroyed the front porch.",
    "🦅 **{name}** arrived via raven delivery with zero rested buff.",
    "🪨 **{name}** joined. 14 Greydwarfs are already furiously tossing pebbles at them.",
    "👹 A Troll with a tree club just heard **{name}** connect and got excited.",
    "⛵ **{name}** logged in! The wind immediately turned against their boat.",
    "🌫️ **{name}** stepped into the realm. Did someone forget their wisp again?",
    "🔥 **{name}** has arrived. Ashlands lava is already calling their name.",
    "🐸 **{name}** entered the server with wet boots and no poison resistance.",
    "🪦 **{name}** logged in to recover their tombstone for the 47th time.",
    "🌾 **{name}** has joined. Please don't run naked through the Plains today.",
    "🔨 **{name}** connected to build a massive fortress and run out of wood in 4 minutes.",
    "🍲 **{name}** arrived at base. Lock the food chests, the scavenger is here!",
    "🐺 **{name}** joined the realm. A 2-star wolf on the mountain is licking its chops.",
    "🏹 **{name}** entered the server with 2 wooden arrows and immense confidence.",
    "🛡️ **{name}** has landed. Time to pretend we have a tactical combat plan!",
    "⛏️ **{name}** joined. Who is ready for 6 hours of mining copper in the dark?",
    "🍄 **{name}** joined the realm in search of red mushrooms and questionable decisions.",
    "🐉 **{name}** logged in. Moder heard their entrance and sneezed a blizzard.",
    "💀 **{name}** is back! Valhalla rejected them again, so back to work!",
    "🌊 **{name}** connected to check if their Karve was sunk by a neck lizard.",
    "🥓 **{name}** entered the world. Somebody get the cauldron boiling!",
    "🗡️ **{name}** unsheathed their bronze sword and accidentally stabbed a workbench.",
    "🌪️ **{name}** has arrived! May their stamina bar last longer than 3 seconds.",
    "🛖 **{name}** joined to fix the roof and fell through the chimney instead.",
    "🦌 **{name}** has spawned. The deer are already honking in terror.",
    "🧙‍♂️ **{name}** entered the realm! Eikthyr's antlers are already trembling.",
    "🪙 **{name}** joined. Haldor the merchant is ready to overcharge them.",
    "🐾 **{name}** arrived to pet the lox and immediately got punted across the field.",
    "🛡️ The horn of Heimdall sounds: **{name}** has arrived to slay (or be slayed)!",
    "🪵 **{name}** entered the server. The physics engine has entered the chat.",
    "⚡ Thor swung Mjolnir in celebration: **{name}** is finally online!",
    "🌾 **{name}** logged on just in time for a Fuling raid on the turnip patch.",
    "🌲 **{name}** spawned in. The Black Forest brutes are sharpening their rocks.",
    "🍻 Raise your horns! **{name}** is back to cause architectural chaos.",
    "✨ **{name}** logged in. Comfort level of the base instantly jumped by +1!",
    "🏆 A true Viking warrior, **{name}**, has entered the tenth realm!"
]

LEAVE_TEMPLATES = [
    "🛡️ **{name}** left the realm. Likely staring at their tombstone in disbelief.",
    "🪵 **{name}** disconnected. A falling birch tree won another 1v1.",
    "🦟 **{name}** got one-shot by a Deathsquito and alt-F4'd into Valhalla.",
    "👹 **{name}** saw 'The Ground is Shaking' and suddenly had dishes to do IRL.",
    "🐺 **{name}** heard 'You are being hunted' and yanked the ethernet cable.",
    "💤 **{name}** went to sleep. Rested buff expired and so did their will to live.",
    "🛌 **{name}** logged off because nighttime in the Black Forest is too spooky.",
    "😴 **{name}** disconnected to touch grass and sleep. The bees miss them already.",
    "⛵ **{name}** left after paddling against headwind for 45 uninterrupted minutes.",
    "🌊 **{name}** drowned in shallow water trying to retrieve 2 copper ore and logged off.",
    "🍖 **{name}** departed to scavenge food in the mysterious IRL biome.",
    "🍻 **{name}** drank too much fermented mead and passed out in the boar pen.",
    "🥩 **{name}** logged off after forgetting to eat and dying to cold damage.",
    "🐗 **{name}** fled the server! A family of 1-star boars chased them off a cliff.",
    "🔨 **{name}** logged off after their stone roof collapsed due to structural physics.",
    "🔥 **{name}** accidentally suffocated in their own smoke-filled longhouse and quit.",
    "🏡 **{name}** realized their wall was 1 snap point off-grid and rage-quit in agony.",
    "🦅 The Valkyrie whisked **{name}** away before the trolls could finish them.",
    "👁️ Odin summoned **{name}** back to do real-world chores.",
    "⚡ **{name}** vanished into the mist. May the wind be at their back next time.",
    "👻 **{name}** left after being jump-scared by a Swamp Wraith at midnight.",
    "🪦 **{name}** disconnected. Body recovery mission scheduled for tomorrow.",
    "🐸 **{name}** got poisoned by an Abomination and logged off to cry in shower.",
    "⛏️ **{name}** broke their third antler pickaxe and gave up on mining.",
    "🌾 **{name}** heard a Fuling giggle behind them and instantly logged out.",
    "🛶 **{name}** ran their longship aground on a rock and logged off out of shame.",
    "🏹 **{name}** missed 12 bow shots on a sitting deer and rage-quit.",
    "🍲 **{name}** raided the food pantry, ate all the serpent stew, and vanished.",
    "🐲 **{name}** got frozen by a Drake and shattered into a million ice cubes.",
    "💀 **{name}** has left the game. Death count: lost track.",
    "🚪 **{name}** closed the wooden door behind them and stepped out of the realm.",
    "🐝 **{name}** signed off. The bees are once again unsupervised.",
    "🧙‍♂️ **{name}** retreated to their IRL sanctuary to recover their stamina."
]

MACRO_ROASTS = {
    # 1. Raid Casualties
    "RAID_CASUALTY_army_theelder": {
        "leave": [
            "🪦 **{name}** disconnected. The Greydwarf raid traumatized them.",
            "🌲 **{name}** fled to desktop! Greydwarfs threw rocks until they lost the will to live.",
            "🪨 **{name}** logged off. Bullied out of the server by angry walking pinecones.",
            "🪵 **{name}** left the realm. The forest moved, and **{name}** moved straight to the exit."
        ],
        "resume": [
            "⚔️ **{name}** is logging back in for revenge against the Greydwarves!",
            "🪵 **{name}** returned with blood in their eyes and an axe for every Greydwarf in the forest.",
            "🌲 **{name}** is back! Time to show those rock-tossing Greydwarfs who owns the realm.",
            "🪓 **{name}** reconnected. Let's see if they can chop Greydwarfs instead of getting pelted."
        ]
    },
    "RAID_CASUALTY_foresttrolls": {
        "leave": [
            "🧌 **{name}** logged off after a blue Troll punted them into the next postal code.",
            "🪵 **{name}** disconnected. Took an entire tree trunk directly to the forehead and rage-quit.",
            "💀 **{name}** left the realm. The longhouse was flattened, and so was their pride.",
            "🪦 **{name}** disconnected. The ground was shaking, and so were their knees."
        ],
        "resume": [
            "🛡️ **{name}** crawled back into the server! Hopefully keeping distance from tree-swinging Trolls.",
            "🏹 **{name}** logged in for Troll retribution! Aim for the head this time!",
            "🧌 **{name}** is back! The Troll that flattened them is still wandering outside, waiting.",
            "⚡ **{name}** returned to avenge the flattened longhouse! Bring fire arrows!"
        ]
    },
    "RAID_CASUALTY_wolves": {
        "leave": [
            "🐺 **{name}** disconnected. 'You are being hunted' turned into 'You became puppy chow'.",
            "🥩 **{name}** left the server after donating all HP to a pack of hungry wolves.",
            "🥶 **{name}** logged off. The wolves were hungry, and **{name}** was the special on the menu."
        ],
        "resume": [
            "🐺 **{name}** is back to turn the wolf pack that ate them into a warm winter cape!",
            "⚔️ **{name}** logged in! Ready to face the mountain predators that humbled them last session.",
            "🥩 **{name}** returned to the mountain! Let's see who bites whom this time."
        ]
    },
    "RAID_CASUALTY_skeletons": {
        "leave": [
            "💀 **{name}** logged off. Skeleton Surprise was definitely not the party they wanted.",
            "🦴 **{name}** disconnected after getting clobbered by angry calcium enthusiasts.",
            "🪦 **{name}** left the realm. Overwhelmed by a horde of smiling skeletons."
        ],
        "resume": [
            "🔨 **{name}** logged in with a blunt club to shatter the skeletons that ambushed them!",
            "💀 **{name}** returned to bury those rattling bones six feet deeper this time.",
            "🦴 **{name}** is back for skeletal vengeance! Bring the Stagbreaker!"
        ]
    },
    "RAID_CASUALTY_army_bonemass": {
        "leave": [
            "☣️ **{name}** disconnected smelling like sewage and green poison. The Swamp won again.",
            "🐸 **{name}** logged off after dissolving into a puddle of swamp slime. Gross."
        ],
        "resume": [
            "🧪 **{name}** chugged poison resistance mead IRL and logged back in to conquer the Swamp!",
            "☣️ **{name}** is back! Scrubbed the swamp mud off and ready to crack some Draugr skulls."
        ]
    },
    "RAID_CASUALTY_army_moder": {
        "leave": [
            "❄️ **{name}** got frozen by mountain Drakes and shattered into ice cubes. Disconnected.",
            "🐉 **{name}** logged off after freezing to death while Drakes laughed from above."
        ],
        "resume": [
            "🔥 **{name}** logged back in with fire arrows to melt those annoying mountain lizards!",
            "🏹 **{name}** returned to the peaks to shoot some Drakes out of the sky!"
        ]
    },
    "RAID_CASUALTY_army_yagluth": {
        "leave": [
            "🌾 **{name}** heard a Fuling giggle, took a spear to the chest, and alt-F4'd into orbit.",
            "👺 **{name}** logged off after getting mobbed by pint-sized goblin maniacs."
        ],
        "resume": [
            "⚔️ **{name}** is back to wipe out every giggling Fuling village on the continent!",
            "🌾 **{name}** returned to the Plains! No mercy for the gigglers this time."
        ]
    },
    "RAID_CASUALTY_GENERIC": {
        "leave": [
            "📯 **{name}** logged off after enemy invaders breached the longhouse. Tactical retreat!",
            "⚔️ **{name}** fell in defense of the hearth and disconnected to nurse battle wounds."
        ],
        "resume": [
            "⚔️ **{name}** returned to reclaim the homestead after that brutal siege!",
            "🛡️ **{name}** is back in the shieldwall! Time to rebuild the broken palisades."
        ]
    },

    # 2. Raid Flawless Defense
    "RAID_SURVIVOR": {
        "leave": [
            "🛡️ **{name}** logged off victorious! Held the shieldwall against the raid without a single scratch.",
            "🍻 **{name}** signed off with hands shaking from battle adrenaline. Time for a celebratory mead!",
            "🏆 **{name}** repelled the enemy siege flawlessly and retired to the mead hall as a champion."
        ],
        "resume": [
            "🏆 The shieldwall hero **{name}** returns! The homestead breathes easier with them online.",
            "⚔️ **{name}** logged in, still riding the high of crushing that siege last time!",
            "🛡️ **{name}** is back! Let's see if the next raid host is foolish enough to test them."
        ]
    },

    # 3. Repeated Deaths / Naked Corpse Run
    "CORPSE_RUN_FAIL": {
        "leave": [
            "💀 **{name}** disconnected. Died, respawned naked with 25 HP, sprinted into danger, and died immediately again.",
            "🪦 **{name}** rage-quit after {deaths} rapid deaths. The naked corpse run defeated their soul.",
            "🏃 **{name}** signed off in pure agony after failing to reach their tombstone for the {deaths}th time.",
            "📉 **{name}** logged off. Skill drain hit hard today: {deaths} deaths in a row!"
        ],
        "resume": [
            "🪦 **{name}** has logged in to attempt tombstone retrieval #{next_death_attempt}. PLEASE wear pants this time!",
            "🏃 **{name}** is back! The naked sprint of shame through the wilderness continues.",
            "🛡️ **{name}** reconnected. Will they actually recover their gear today, or leave behind tombstone #{next_death_attempt}?",
            "🥩 **{name}** logged in! Somebody please give them food so they don't die with 25 HP again."
        ]
    },

    # 4. Rage-Quit After Death
    "RAGE_QUIT": {
        "leave": [
            "🔌 **{name}** died and instantly yanked the ethernet cord. Alt-F4 in pure fury!",
            "🤬 **{name}** disconnected seconds after taking a fatal hit. Pray for their keyboard and desk.",
            "💥 **{name}** rage-quit to desktop. Estimated salt saturation: 100%.",
            "💨 **{name}** died and vanished faster than smoke from an unventilated fireplace."
        ],
        "resume": [
            "🔌 **{name}** has cooled off and reconnected! Let's pretend that violent rage-quit never happened.",
            "🧘 **{name}** logged in! Blood pressure has returned to normal and the monitor is still in one piece.",
            "💀 **{name}** crawled back after rage-quitting. That grave isn't going to loot itself, warrior.",
            "🕊️ **{name}** returned in peace. Anger management session complete!"
        ]
    },

    # 5. Wilderness / Exploration Death
    "WILDERNESS_DEATH": {
        "leave": [
            "🌲 **{name}** logged off after meeting the fatal business end of a falling birch tree.",
            "💀 **{name}** disconnected after taking a dirt nap in the wilderness. Valhalla rejected their application.",
            "🧗 **{name}** signed off after forgetting to eat sausages and falling off a cliff with 25 HP.",
            "🪵 **{name}** logged off. Tree physics 1, Viking 0."
        ],
        "resume": [
            "🌲 **{name}** is back to show the forest that falling timber won't stop them forever!",
            "🍖 **{name}** logged in! Somebody feed this Viking meat before they die of starvation again.",
            "🗡️ **{name}** returned to settle the score with whatever creature humbled them earlier!",
            "🪓 **{name}** logged in with an axe and a vendetta against every birch tree in the realm."
        ]
    },

    # 6. Boss Slayer
    "BOSS_SLAYER": {
        "leave": [
            "👑 **{name}** logged off a mythic champion after vanquishing a dread lord of the realm!",
            "🏆 **{name}** retired to feast after sending a boss screaming back to the underworld."
        ],
        "resume": [
            "⚡ All hail **{name}**! The boss slayer returns to claim more glory from Odin.",
            "🍻 **{name}** logged in! Raise your drinking horns for the conqueror of legends!"
        ]
    },

    # 7. Marathon Grinder / Builder
    "MARATHON_GRIND": {
        "leave": [
            "🔨 **{name}** logged off after {duration_mins}m of obsessive building. The chimney is finally 1 snap-point aligned.",
            "⛏️ **{name}** disconnected after {duration_mins}m of mining copper in the rain. Go touch grass!",
            "🐝 **{name}** signed off after a {duration_mins}m marathon session. The bees are officially happy.",
            "🪵 **{name}** deforested half the biome over {duration_mins} minutes and finally logged off."
        ],
        "resume": [
            "🔨 **{name}** logged in! Time to build another unnecessarily elaborate balcony on the longhouse.",
            "⛏️ **{name}** is back! Who's ready for another 3 hours of hitting rocks in the dark?",
            "🏡 The master architect **{name}** has returned to fix the crooked walls.",
            "🪵 **{name}** is back! The trees are trembling in fear of their woodcutting addiction."
        ]
    },

    # 8. Quick Dip / Coward Retreat
    "QUICK_DIP": {
        "leave": [
            "👀 **{name}** dipped after only {duration_mins}m. Spawned, saw nighttime, and noped right out.",
            "🚪 **{name}** logged off after {duration_mins}m. Did they just come in to smell the mead?",
            "💨 **{name}** vanished after {duration_mins}m. Fastest in-and-out in Viking history."
        ],
        "resume": [
            "👀 **{name}** is back! Taking bets on whether they stay longer than 3 minutes this time.",
            "🚪 **{name}** returned! Let's see if this visit lasts longer than a Greydwarf pebble toss.",
            "⏱️ **{name}** has joined. Stopwatch is running!"
        ]
    },

    # 9. Peaceful Standard Exit
    "PEACEFUL_LOGOUT": {
        "leave": [
            "🛡️ **{name}** sheathed their blade and stepped out of the realm. A respectable {duration_mins}m session.",
            "🌙 **{name}** logged off to rest. The hearth fires keep the longhouse warm.",
            "🥩 **{name}** logged out with a full belly and dry boots. Until next time, warrior!",
            "💤 **{name}** went to sleep. Rested buff expired and so did their energy."
        ],
        "resume": [
            "⚔️ **{name}** returned to the tenth realm! Sharpen your axes and grab some stew.",
            "✨ **{name}** has arrived at base. Comfort level instantly jumped +1!",
            "🔥 **{name}** kicked the tavern doors open ready for the next adventure!"
        ]
    }
}

def format_roast(template: str, name: str, extra: Optional[Dict[str, Any]] = None) -> str:
    """Safely formats a roast template preventing KeyError or dangling braces."""
    kwargs = {"name": name}
    if extra:
        kwargs.update(extra)
    formatted = template.format_map(SafeFormatDict(**kwargs))
    return re.sub(r'\{[a-zA-Z0-9_]+\}', '', formatted)

def get_random_join(name: str) -> str:
    tmpl = random.choice(JOIN_TEMPLATES)
    return format_roast(tmpl, name)

def get_random_leave(name: str) -> str:
    tmpl = random.choice(LEAVE_TEMPLATES)
    return format_roast(tmpl, name)

def get_session_leave_message(name: str, event_type: str, session_data: Optional[Dict[str, Any]] = None) -> str:
    """Selects a context-aware roast based on what happened in the player's active session."""
    session_data = session_data or {}
    duration_mins = session_data.get("duration_mins", 1)
    deaths = session_data.get("deaths_count", 0)
    detail = session_data.get("event_detail", {})
    raid_key = detail.get("raid_key") if isinstance(detail, dict) else None

    roast_group = None
    if event_type == "RAID_CASUALTY":
        specific_key = f"RAID_CASUALTY_{raid_key}" if raid_key else None
        if specific_key and specific_key in MACRO_ROASTS:
            roast_group = MACRO_ROASTS[specific_key]
        else:
            roast_group = MACRO_ROASTS.get("RAID_CASUALTY_GENERIC")
    elif event_type in MACRO_ROASTS:
        roast_group = MACRO_ROASTS[event_type]

    candidates = []
    if roast_group and "leave" in roast_group:
        candidates.extend(roast_group["leave"])

    if candidates:
        template = random.choice(candidates)
        return format_roast(
            template,
            name=name,
            extra={
                "duration_mins": duration_mins,
                "minutes": duration_mins,
                "hours": round(duration_mins / 60, 1),
                "deaths": deaths,
                "deaths_count": deaths,
                "next_death_attempt": max(2, deaths + 1)
            }
        )
    return get_random_leave(name)

def get_session_resume_message(name: str, last_state: Optional[Dict[str, Any]] = None) -> str:
    """Selects a revenge or comeback roast referencing what happened in their previous session."""
    if not last_state:
        return get_random_join(name)

    event_type = last_state.get("event_type", "PEACEFUL_LOGOUT")
    detail = last_state.get("event_detail", {})
    raid_key = detail.get("raid_key") if isinstance(detail, dict) else None
    duration_mins = last_state.get("duration_mins", 1)
    deaths = last_state.get("deaths_count", 0)

    roast_group = None
    if event_type == "RAID_CASUALTY":
        specific_key = f"RAID_CASUALTY_{raid_key}" if raid_key else None
        if specific_key and specific_key in MACRO_ROASTS:
            roast_group = MACRO_ROASTS[specific_key]
        else:
            roast_group = MACRO_ROASTS.get("RAID_CASUALTY_GENERIC")
    elif event_type in MACRO_ROASTS:
        roast_group = MACRO_ROASTS[event_type]

    candidates = []
    if roast_group and "resume" in roast_group:
        candidates.extend(roast_group["resume"])

    if candidates:
        template = random.choice(candidates)
        return format_roast(
            template,
            name=name,
            extra={
                "duration_mins": duration_mins,
                "deaths": deaths,
                "next_death_attempt": max(2, deaths + 1)
            }
        )
    return get_random_join(name)
