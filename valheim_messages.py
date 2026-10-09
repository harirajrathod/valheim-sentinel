"""
/root/valheim_messages.py - Context-Aware, Session-Linked Valheim Player Join & Leave Roasts
"""

import random
import re
import os
import json
import sys

sys.path.insert(0, "/root")
from valheim_utils import (
    format_player_name,
    safe_format_template,
    safe_load_json
)

JOIN_TEMPLATES = [
    "⚔️ [Valheim] *{name}* dropped into the realm! Watch out for falling timber!",
    "🌲 [Valheim] *{name}* has joined. Hide your trees before they crush your longhouse!",
    "🐝 [Valheim] *{name}* joined the server. The bees are... mildly concerned.",
    "🍯 [Valheim] *{name}* has arrived to inspect if the bees are happy!",
    "🦟 [Valheim] *{name}* logged in. Somewhere in the Plains, a Deathsquito just smiled.",
    "🍖 [Valheim] *{name}* spawned with 25 HP and an empty belly. Someone cook sausages!",
    "🍻 [Valheim] *{name}* kicked the tavern doors open demanding tasty mead!",
    "🐗 [Valheim] *{name}* has entered the realm. Reminder: Boar loves you.",
    "⚡ [Valheim] The Valkyrie dropped *{name}* face-first onto the sacrificial altar.",
    "👁️ [Valheim] Odin peered through the clouds, sighed, and muttered: 'Oh great, *{name}* is back.'",
    "🪓 [Valheim] *{name}* logged in to chop trees and accidentally destroyed the front porch.",
    "🦅 [Valheim] *{name}* arrived via raven delivery with zero rested buff.",
    "🪨 [Valheim] *{name}* joined. 14 Greydwarfs are already furiously tossing pebbles at them.",
    "👹 [Valheim] A Troll with a tree club just heard *{name}* connect and got excited.",
    "⛵ [Valheim] *{name}* logged in! The wind immediately turned against their boat.",
    "🌫️ [Valheim] *{name}* stepped into the realm. Did someone forget their wisp again?",
    "🔥 [Valheim] *{name}* has arrived. Ashlands lava is already calling their name.",
    "🐸 [Valheim] *{name}* entered the server with wet boots and no poison resistance.",
    "🪦 [Valheim] *{name}* logged in to recover their tombstone for the 47th time.",
    "🌾 [Valheim] *{name}* has joined. Please don't run naked through the Plains today.",
    "🔨 [Valheim] *{name}* connected to build a massive fortress and run out of wood in 4 minutes.",
    "🍲 [Valheim] *{name}* arrived at base. Lock the food chests, the scavenger is here!",
    "🐺 [Valheim] *{name}* joined the realm. A 2-star wolf on the mountain is licking its chops.",
    "🏹 [Valheim] *{name}* entered the server with 2 wooden arrows and immense confidence.",
    "🛡️ [Valheim] *{name}* has landed. Time to pretend we have a tactical combat plan!",
    "⛏️ [Valheim] *{name}* joined. Who is ready for 6 hours of mining copper in the dark?",
    "🍄 [Valheim] *{name}* joined the realm in search of red mushrooms and questionable decisions.",
    "🐉 [Valheim] *{name}* logged in. Moder heard their entrance and sneezed a blizzard.",
    "💀 [Valheim] *{name}* is back! Valhalla rejected them again, so back to work!",
    "🌊 [Valheim] *{name}* connected to check if their Karve was sunk by a neck lizard.",
    "🥓 [Valheim] *{name}* entered the world. Somebody get the cauldron boiling!",
    "🗡️ [Valheim] *{name}* unsheathed their bronze sword and accidentally stabbed a workbench.",
    "🌪️ [Valheim] *{name}* has arrived! May their stamina bar last longer than 3 seconds.",
    "🛖 [Valheim] *{name}* joined to fix the roof and fell through the chimney instead.",
    "🦌 [Valheim] *{name}* has spawned. The deer are already honking in terror.",
    "🧙‍♂️ [Valheim] *{name}* entered the realm! Eikthyr's antlers are already trembling.",
    "🔥 [Valheim] *{name}* joined. Who forgot to build a chimney? It smells like smoke already.",
    "🥩 [Valheim] *{name}* logged in. Say goodbye to the serpent meat in chest #4!",
    "⚔️ [Valheim] A wild *{name}* appeared! They look cold and hungry.",
    "🛶 [Valheim] *{name}* set sail into the server. Watch out for sea serpents!",
    "🪙 [Valheim] *{name}* joined. Haldor the merchant is ready to overcharge them.",
    "🐾 [Valheim] *{name}* arrived to pet the lox and immediately got punted across the field.",
    "🛡️ [Valheim] The horn of Heimdall sounds: *{name}* has arrived to slay (or be slayed)!",
    "🪵 [Valheim] *{name}* entered the server. The physics engine has entered the chat.",
    "⚡ [Valheim] Thor swung Mjolnir in celebration: *{name}* is finally online!",
    "🌾 [Valheim] *{name}* logged on just in time for a Fuling raid on the turnip patch.",
    "🌲 [Valheim] *{name}* spawned in. The Black Forest brutes are sharpening their rocks.",
    "🍻 [Valheim] Raise your horns! *{name}* is back to cause architectural chaos.",
    "✨ [Valheim] *{name}* logged in. Comfort level of the base instantly jumped by +1!",
    "🏆 [Valheim] A true Viking warrior, *{name}*, has entered the tenth realm!"
]

LEAVE_TEMPLATES = [
    "🛡️ [Valheim] *{name}* left the realm. Likely staring at their tombstone in disbelief.",
    "🪵 [Valheim] *{name}* disconnected. A falling birch tree won another 1v1.",
    "🦟 [Valheim] *{name}* got one-shot by a Deathsquito and alt-F4'd into Valhalla.",
    "👹 [Valheim] *{name}* saw 'The Ground is Shaking' and suddenly had dishes to do IRL.",
    "🐺 [Valheim] *{name}* heard 'You are being hunted' and yanked the ethernet cable.",
    "💤 [Valheim] *{name}* went to sleep. Rested buff expired and so did their will to live.",
    "🛌 [Valheim] *{name}* logged off because nighttime in the Black Forest is too spooky.",
    "😴 [Valheim] *{name}* disconnected to touch grass and sleep. The bees miss them already.",
    "⛵ [Valheim] *{name}* left after paddling against headwind for 45 uninterrupted minutes.",
    "🌊 [Valheim] *{name}* drowned in shallow water trying to retrieve 2 copper ore and logged off.",
    "🍖 [Valheim] *{name}* departed to scavenge food in the mysterious IRL biome.",
    "🍻 [Valheim] *{name}* drank too much fermented mead and passed out in the boar pen.",
    "🥩 [Valheim] *{name}* logged off after forgetting to eat and dying to cold damage.",
    "🐗 [Valheim] *{name}* fled the server! A family of 1-star boars chased them off a cliff.",
    "🔨 [Valheim] *{name}* logged off after their stone roof collapsed due to structural physics.",
    "🔥 [Valheim] *{name}* accidentally suffocated in their own smoke-filled longhouse and quit.",
    "🏡 [Valheim] *{name}* realized their wall was 1 snap point off-grid and rage-quit in agony.",
    "🦅 [Valheim] The Valkyrie whisked *{name}* away before the trolls could finish them.",
    "👁️ [Valheim] Odin summoned *{name}* back to do real-world chores.",
    "⚡ [Valheim] *{name}* vanished into the mist. May the wind be at their back next time.",
    "👻 [Valheim] *{name}* left after being jump-scared by a Swamp Wraith at midnight.",
    "🪦 [Valheim] *{name}* disconnected. Body recovery mission scheduled for tomorrow.",
    "🐸 [Valheim] *{name}* got poisoned by an Abomination and logged off to cry in shower.",
    "⛏️ [Valheim] *{name}* broke their third antler pickaxe and gave up on mining.",
    "🌾 [Valheim] *{name}* heard a Fuling giggle behind them and instantly logged out.",
    "🛶 [Valheim] *{name}* ran their longship aground on a rock and logged off out of shame.",
    "🏹 [Valheim] *{name}* missed 12 bow shots on a sitting deer and rage-quit.",
    "🍲 [Valheim] *{name}* raided the food pantry, ate all the serpent stew, and vanished.",
    "🐲 [Valheim] *{name}* got frozen by a Drake and shattered into a million ice cubes.",
    "💀 [Valheim] *{name}* has left the game. Death count: lost track.",
    "🚪 [Valheim] *{name}* closed the wooden door behind them and stepped out of the realm.",
    "🐝 [Valheim] *{name}* signed off. The bees are once again unsupervised.",
    "🧙‍♂️ [Valheim] *{name}* retreated to their IRL sanctuary to recover their stamina.",
    "🍂 [Valheim] *{name}* disappeared like a greydwarf into the autumn brush.",
    "⚔️ [Valheim] *{name}* sheathed their blade and logged out. Valhalla awaits another day.",
    "🛡️ [Valheim] *{name}* dropped their shield and retreated to the comfort of warm blankets.",
    "🔥 [Valheim] *{name}* stepped on a campfire, caught fire, panicked, and disconnected.",
    "🐖 [Valheim] *{name}* logged off. The tamed boars are squealing in sorrow.",
    "✨ [Valheim] *{name}* vanished. Comfort level of the longhouse dropped by -1.",
    "🪓 [Valheim] *{name}* felled one last oak tree, it landed on their head, and they logged off.",
    "🪙 [Valheim] *{name}* went bankrupt trading with Haldor and logged off in poverty.",
    "🌲 [Valheim] *{name}* ran out of stamina running uphill and accepted their fate. Disconnected.",
    "🥘 [Valheim] *{name}* left to grab actual dinner instead of staring at cooked neck tails.",
    "🥶 [Valheim] *{name}* froze to death on a mountain peak looking for silver and signed off.",
    "⚡ [Valheim] *{name}* logged off. The thunderstorm slowly clears.",
    "👹 [Valheim] *{name}* got smacked by a troll club into the next postal code. Left server.",
    "🦇 [Valheim] *{name}* survived 'A stirred the cauldron' raid and logged off to breathe.",
    "⛵ [Valheim] *{name}* left the docks. The longship waits for their return.",
    "🌙 [Valheim] Night has fallen, and *{name}* has escaped to the safety of sleep.",
    "🏆 [Valheim] *{name}* hung up their battleaxe. Until next time, brave warrior!"
]

MACRO_ROASTS = {
    # 1. Raid Casualties by specific raid
    "RAID_CASUALTY_army_theelder": {
        "leave": [
            "🪦 [Valheim] *{name}* disconnected. The Greydwarf raid traumatized him.",
            "🌲 [Valheim] *{name}* fled to desktop! Greydwarfs threw rocks at his face until he lost the will to live.",
            "🪨 [Valheim] *{name}* logged off. Bullied out of the server by a pack of angry walking pinecones.",
            "🪵 [Valheim] *{name}* left the realm. The forest moved, and *{name}* moved straight to the exit."
        ],
        "resume": [
            "⚔️ [Valheim] *{name}* is logging back in for revenge against the Greydwarves!",
            "🪵 [Valheim] *{name}* returned with blood in his eyes and an axe for every Greydwarf in the Black Forest.",
            "🌲 [Valheim] *{name}* is back! Time to show those rock-tossing Greydwarfs who actually owns the realm.",
            "🪓 [Valheim] *{name}* reconnected. Let's see if he can chop Greydwarfs instead of getting pelted with pebbles."
        ]
    },
    "RAID_CASUALTY_foresttrolls": {
        "leave": [
            "🧌 [Valheim] *{name}* logged off after a blue Troll punted him into the next postal code.",
            "🪵 [Valheim] *{name}* disconnected. Took an entire tree trunk directly to the forehead and rage-quit.",
            "💀 [Valheim] *{name}* left the realm. The longhouse was partially flattened, and so was his pride.",
            "🪦 [Valheim] *{name}* disconnected. The ground was shaking, and so were his knees."
        ],
        "resume": [
            "🛡️ [Valheim] *{name}* crawled back into the server! Hopefully keeping his distance from tree-swinging Trolls this time.",
            "🏹 [Valheim] *{name}* logged in for Troll retribution! Aim for the head this time!",
            "🧌 [Valheim] *{name}* is back! The Troll that flattened him earlier is still wandering outside, waiting.",
            "⚡ [Valheim] *{name}* returned to avenge his flattened longhouse! Bring fire arrows!"
        ]
    },
    "RAID_CASUALTY_wolves": {
        "leave": [
            "🐺 [Valheim] *{name}* disconnected. 'You are being hunted' turned into 'You became puppy chow'.",
            "🥩 [Valheim] *{name}* left the server after donating all his HP to a pack of hungry wolves.",
            "🥶 [Valheim] *{name}* logged off. The wolves were hungry, and *{name}* was the special on the menu."
        ],
        "resume": [
            "🐺 [Valheim] *{name}* is back to turn the wolf pack that ate him into a warm winter cape!",
            "⚔️ [Valheim] *{name}* logged in! Ready to face the mountain predators that humbled him last session.",
            "🥩 [Valheim] *{name}* returned to the mountain! Let's see who bites whom this time."
        ]
    },
    "RAID_CASUALTY_skeletons": {
        "leave": [
            "💀 [Valheim] *{name}* logged off. The Skeleton Surprise was definitely not the kind of party he wanted.",
            "🦴 [Valheim] *{name}* disconnected after getting clobbered by a gang of angry calcium enthusiasts.",
            "🪦 [Valheim] *{name}* left the realm. Overwhelmed by a horde of smiling skeletons."
        ],
        "resume": [
            "🔨 [Valheim] *{name}* logged in with a blunt club to shatter the skeletons that ambushed him!",
            "💀 [Valheim] *{name}* returned to bury those rattling bones six feet deeper this time.",
            "🦴 [Valheim] *{name}* is back for skeletal vengeance! Bring the stagbreaker!"
        ]
    },
    "RAID_CASUALTY_bats": {
        "leave": [
            "🦇 [Valheim] *{name}* logged off in pure disgust after getting nibbled to death by cave bats.",
            "🩸 [Valheim] *{name}* disconnected. You stirred the cauldron, and the bats stirred his grave."
        ],
        "resume": [
            "🦇 [Valheim] *{name}* logged in with a torch to exterminate the flying rodents that harassed him!",
            "🔥 [Valheim] *{name}* returned with fire arrows! Death to the cauldron bats!"
        ]
    },
    "RAID_CASUALTY_army_bonemass": {
        "leave": [
            "☣️ [Valheim] *{name}* disconnected smelling like sewage and green poison. The Swamp won again.",
            "🐸 [Valheim] *{name}* logged off after dissolving into a puddle of swamp slime. Gross."
        ],
        "resume": [
            "🧪 [Valheim] *{name}* chugged poison resistance mead IRL and logged back in to conquer the Swamp!",
            "☣️ [Valheim] *{name}* is back! Scrubbed the swamp mud off and ready to crack some Draugr skulls."
        ]
    },
    "RAID_CASUALTY_army_eikthyr": {
        "leave": [
            "🐗 [Valheim] *{name}* disconnected. Eikthyr rallied the forest boars and *{name}* got gored into next week.",
            "⚡ [Valheim] *{name}* left after getting trampled by angry woodland creatures in the Meadows."
        ],
        "resume": [
            "🥓 [Valheim] *{name}* logged in with a frying pan! Those boars are turning into bacon today.",
            "🏹 [Valheim] *{name}* returned to show Eikthyr's woodland army who the real predator is!"
        ]
    },
    "RAID_CASUALTY_army_moder": {
        "leave": [
            "❄️ [Valheim] *{name}* got frozen by mountain Drakes and shattered into ice cubes. Disconnected.",
            "🐉 [Valheim] *{name}* logged off after freezing to death while Drakes laughed from above."
        ],
        "resume": [
            "🔥 [Valheim] *{name}* logged back in with fire arrows to melt those annoying mountain lizards!",
            "🏹 [Valheim] *{name}* returned to the peaks to shoot some Drakes out of the sky!"
        ]
    },
    "RAID_CASUALTY_army_yagluth": {
        "leave": [
            "🌾 [Valheim] *{name}* heard a Fuling giggle, took a spear to the chest, and alt-F4'd into orbit.",
            "👺 [Valheim] *{name}* logged off after getting mobbed by pint-sized goblin maniacs."
        ],
        "resume": [
            "⚔️ [Valheim] *{name}* is back to wipe out every giggling Fuling village on the continent!",
            "🌾 [Valheim] *{name}* returned to the Plains! No mercy for the gigglers this time."
        ]
    },
    "RAID_CASUALTY_army_queen": {
        "leave": [
            "🪲 [Valheim] *{name}* got swarmed by giant Mistland bugs and disconnected in absolute horror.",
            "🕸️ [Valheim] *{name}* logged off after becoming Seeker chow in the dark mist."
        ],
        "resume": [
            "🗡️ [Valheim] *{name}* stepped back into the mist with heavy steel to squash some giant bugs!",
            "🪲 [Valheim] *{name}* returned! The exterminator has arrived for the Seekers."
        ]
    },
    "RAID_CASUALTY_army_fader": {
        "leave": [
            "🔥 [Valheim] *{name}* got turned into extra-crispy Viking toast by the Charred legion. Logged off.",
            "🌋 [Valheim] *{name}* disconnected. Ashlands heat and skeleton armies melted his will to live."
        ],
        "resume": [
            "🛡️ [Valheim] *{name}* returned to the burning ash to claim vengeance on the Charred horde!",
            "🔥 [Valheim] *{name}* logged in! Cold water drank, ready to march back into the inferno."
        ]
    },
    "RAID_CASUALTY_GENERIC": {
        "leave": [
            "📯 [Valheim] *{name}* logged off after enemy invaders breached the longhouse. Tactical retreat!",
            "⚔️ [Valheim] *{name}* fell in defense of the hearth and disconnected to nurse his battle wounds."
        ],
        "resume": [
            "⚔️ [Valheim] *{name}* returned to reclaim the homestead after that brutal siege!",
            "🛡️ [Valheim] *{name}* is back in the shieldwall! Time to rebuild the broken palisades."
        ]
    },

    # 2. Raid Flawless Defense
    "RAID_SURVIVOR": {
        "leave": [
            "🛡️ [Valheim] *{name}* logged off victorious! Held the shieldwall against the raid without a single scratch.",
            "🍻 [Valheim] *{name}* signed off with hands shaking from battle adrenaline. Time for a celebratory mead!",
            "🏆 [Valheim] *{name}* repelled the enemy siege flawlessly and retired to the mead hall as a champion."
        ],
        "resume": [
            "🏆 [Valheim] The shieldwall hero *{name}* returns! The homestead breathes easier with him online.",
            "⚔️ [Valheim] *{name}* logged in, still riding the high of crushing that siege last time!",
            "🛡️ [Valheim] *{name}* is back! Let's see if the next raid host is foolish enough to test him."
        ]
    },

    # 3. Repeated Deaths / Naked Corpse Run
    "CORPSE_RUN_FAIL": {
        "leave": [
            "💀 [Valheim] *{name}* disconnected. Died, respawned naked with 25 HP, sprinted into danger, and died immediately again.",
            "🪦 [Valheim] *{name}* rage-quit after {deaths} rapid deaths. The naked corpse run defeated his soul.",
            "🏃 [Valheim] *{name}* signed off in pure agony after failing to recover their tombstone after {deaths} attempts.",
            "📉 [Valheim] *{name}* logged off. Skill drain hit hard today: {deaths} deaths in a row!"
        ],
        "resume": [
            "🪦 [Valheim] *{name}* has logged in to attempt tombstone retrieval #{next_death_attempt}. PLEASE wear pants this time!",
            "🏃 [Valheim] *{name}* is back! The naked sprint of shame through the wilderness continues.",
            "🛡️ [Valheim] *{name}* reconnected. Will he actually recover his gear today, or leave behind tombstone #{next_death_attempt}?",
            "🥩 [Valheim] *{name}* logged in! Somebody please give him food so he doesn't die with 25 HP again."
        ]
    },

    # 4. Rage-Quit After Death
    "RAGE_QUIT": {
        "leave": [
            "🔌 [Valheim] *{name}* died and instantly yanked the ethernet cord. Alt-F4 in pure fury!",
            "🤬 [Valheim] *{name}* disconnected seconds after taking a fatal hit. Pray for his keyboard and desk.",
            "💥 [Valheim] *{name}* rage-quit to desktop. Estimated salt saturation: 100%.",
            "💨 [Valheim] *{name}* died and vanished faster than smoke from an unventilated fireplace."
        ],
        "resume": [
            "🔌 [Valheim] *{name}* has cooled off and reconnected! Let's pretend that violent rage-quit never happened.",
            "🧘 [Valheim] *{name}* logged in! Blood pressure has returned to normal and the monitor is still in one piece.",
            "💀 [Valheim] *{name}* crawled back after rage-quitting. That grave isn't going to loot itself, warrior.",
            "🕊️ [Valheim] *{name}* returned in peace. Anger management session complete!"
        ]
    },

    # 5. Wilderness / Exploration Death
    "WILDERNESS_DEATH": {
        "leave": [
            "🌲 [Valheim] *{name}* logged off after meeting the fatal business end of a falling birch tree.",
            "💀 [Valheim] *{name}* disconnected after taking a dirt nap in the wilderness. Valhalla rejected his application.",
            "🧗 [Valheim] *{name}* signed off after forgetting to eat sausages and falling off a cliff with 25 HP.",
            "🪵 [Valheim] *{name}* logged off. Tree physics 1, Viking 0."
        ],
        "resume": [
            "🌲 [Valheim] *{name}* is back to show the forest that falling timber won't stop him forever!",
            "🍖 [Valheim] *{name}* logged in! Somebody feed this Viking meat before he dies of starvation again.",
            "🗡️ [Valheim] *{name}* returned to settle the score with whatever creature humbled him earlier!",
            "🪓 [Valheim] *{name}* logged in with an axe and a vendetta against every birch tree in the realm."
        ]
    },

    # 6. Dungeon / Crypt Crawler
    "DUNGEON_CRAWLER": {
        "leave": [
            "🗝️ [Valheim] *{name}* logged off after plundering dark crypts. Smells like rotting Draugr and muddy scrap iron.",
            "⛏️ [Valheim] *{name}* disconnected with full pockets and broken pickaxes from deep underground.",
            "🏰 [Valheim] *{name}* left the realm with mud all over his armor. Dungeon expedition complete!"
        ],
        "resume": [
            "⛏️ [Valheim] *{name}* logged in to haul that mountain of dungeon iron back to the smelter!",
            "🗝️ [Valheim] *{name}* is back to crawl through more damp, muddy dungeons in search of loot.",
            "💰 [Valheim] The dungeon looter *{name}* returns! Let's see what treasures he brought back."
        ]
    },

    # 7. Boss Slayer
    "BOSS_SLAYER": {
        "leave": [
            "👑 [Valheim] *{name}* logged off a mythic champion after vanquishing a dread lord of the realm!",
            "🏆 [Valheim] *{name}* retired to feast after sending a boss screaming back to the underworld."
        ],
        "resume": [
            "⚡ [Valheim] All hail *{name}*! The boss slayer returns to claim more glory from Odin.",
            "🍻 [Valheim] *{name}* logged in! Raise your drinking horns for the conqueror of legends!"
        ]
    },

    # 8. Marathon Grinder / Builder
    "MARATHON_GRIND": {
        "leave": [
            "🔨 [Valheim] *{name}* logged off after {duration_mins}m of obsessive building. The chimney is finally 1 snap-point aligned.",
            "⛏️ [Valheim] *{name}* disconnected after {duration_mins}m of mining copper in the rain. Go touch grass!",
            "🐝 [Valheim] *{name}* signed off after a {duration_mins}m marathon session. The bees are officially happy.",
            "🪵 [Valheim] *{name}* deforested half the biome over {duration_mins} minutes and finally logged off."
        ],
        "resume": [
            "🔨 [Valheim] *{name}* logged in! Time to build another unnecessarily elaborate balcony on the longhouse.",
            "⛏️ [Valheim] *{name}* is back! Who's ready for another 3 hours of hitting rocks in the dark?",
            "🏡 [Valheim] The master architect *{name}* has returned to fix the crooked walls.",
            "🪵 [Valheim] *{name}* is back! The trees are trembling in fear of his woodcutting addiction."
        ]
    },

    # 9. Quick Dip / Coward Retreat
    "QUICK_DIP": {
        "leave": [
            "👀 [Valheim] *{name}* dipped after only {duration_mins}m. Spawned, saw nighttime, and noped right out.",
            "🚪 [Valheim] *{name}* logged off after {duration_mins}m. Did they just come in to smell the mead?",
            "💨 [Valheim] *{name}* vanished after {duration_mins}m. Fastest in-and-out in Viking history."
        ],
        "resume": [
            "👀 [Valheim] *{name}* is back! Taking bets on whether he stays longer than 3 minutes this time.",
            "🚪 [Valheim] *{name}* returned! Let's see if this visit lasts longer than a Greydwarf pebble toss.",
            "⏱️ [Valheim] *{name}* has joined. Stopwatch is running!"
        ]
    },

    # 10. Peaceful Standard Exit
    "PEACEFUL_LOGOUT": {
        "leave": [
            "🛡️ [Valheim] *{name}* sheathed their blade and stepped out of the realm. A respectable {duration_mins}m session.",
            "🌙 [Valheim] *{name}* logged off to rest. The hearth fires keep the longhouse warm.",
            "🥩 [Valheim] *{name}* logged out with a full belly and dry boots. Until next time, warrior!",
            "💤 [Valheim] *{name}* went to sleep. Rested buff expired and so did their energy."
        ],
        "resume": [
            "⚔️ [Valheim] *{name}* returned to the tenth realm! Sharpen your axes and grab some stew.",
            "✨ [Valheim] *{name}* has arrived at base. Comfort level instantly jumped +1!",
            "🔥 [Valheim] *{name}* kicked the tavern doors open ready for the next adventure!",
            "🍺 [Valheim] *{name}* is back! Pour a horn of mead and rally to the hearth."
        ]
    },

    # 11. Sea Voyage / Sailing Expedition
    "SEA_VOYAGE": {
        "leave": [
            "⛵ [Valheim] *{name}* logged off after paddling against headwind for {duration_mins} uninterrupted minutes.",
            "🌊 [Valheim] *{name}* disconnected with soaking wet boots and salt in his beard. Oceanic expedition complete!",
            "🐍 [Valheim] *{name}* dropped anchor on distant shores and signed off before a Sea Serpent could smell him.",
            "🛶 [Valheim] *{name}* tied the boat to the dock and retired to the tavern after a long oceanic voyage."
        ],
        "resume": [
            "🧭 [Valheim] Captain *{name}* has returned to helm the ship! May the wind actually be at his back today.",
            "⛵ [Valheim] *{name}* is back in the realm! Grab an oar—the maritime fleet is setting sail.",
            "🌊 [Valheim] *{name}* logged in! Rested buff acquired IRL, ready to brave the open seas again.",
            "🗺️ [Valheim] The great navigator *{name}* has returned! New uncharted continents await."
        ]
    },

    # 12. Sea Casualty / Shipwreck / Drowning
    "SEA_CASUALTY": {
        "leave": [
            "🌊 [Valheim] *{name}* met Davy Jones! Capsized or drowned during an ocean voyage. Disconnected in despair.",
            "🐍 [Valheim] *{name}* sailed into the deep ocean and became Sea Serpent snacks. Alt-F4'd in sorrow.",
            "⛵ [Valheim] *{name}* logged off. His boat is at the bottom of the ocean, and so is his dignity."
        ],
        "resume": [
            "⛵ [Valheim] *{name}* returned to build a rescue raft to salvage his sunken gear from the ocean floor!",
            "🌊 [Valheim] *{name}* is back! Swimming lessons complete, ready to face the ocean waves again.",
            "🏊 [Valheim] *{name}* logged in! Let's see if he can stay inside the boat this time."
        ]
    }
}


def format_player_name(name: str) -> str:
    if not name:
        return ""
    if name.strip().lower() in ("musashi", "musashi(musa bhai)", "musa bhai"):
        return "Musashi(Musa Bhai)"
    return name


def get_random_join_message(name: str, target: str = "whatsapp") -> str:
    name = format_player_name(name)
    template = random.choice(JOIN_TEMPLATES)
    msg = safe_format_template(template, name=name)
    if target == "telegram":
        msg = re.sub(r'\*([^*]+)\*', r'<b>\1</b>', msg)
    return msg


def get_random_leave_message(name: str, target: str = "whatsapp") -> str:
    name = format_player_name(name)
    template = random.choice(LEAVE_TEMPLATES)
    msg = safe_format_template(template, name=name)
    if target == "telegram":
        msg = re.sub(r'\*([^*]+)\*', r'<b>\1</b>', msg)
    return msg


DYNAMIC_ROASTS_FILE = "/root/valheim_dynamic_roasts.json"

def load_dynamic_roasts() -> dict:
    return safe_load_json(DYNAMIC_ROASTS_FILE, default={})


FEMALE_WARRIORS = {"hilda", "faye", "rukia"}

class SafeFormatDict(dict):
    def __missing__(self, key):
        return ""

def format_roast_template(template: str, **kwargs) -> str:
    name = str(kwargs.get("name", ""))
    is_female = any(fem in name.lower() for fem in FEMALE_WARRIORS)
    try:
        formatted = template.format_map(SafeFormatDict(**kwargs))
        formatted = re.sub(r'\{[a-zA-Z0-9_]+\}', '', formatted)
    except Exception:
        msg = template
        for k, v in kwargs.items():
            msg = msg.replace(f"{{{k}}}", str(v))
        formatted = re.sub(r'\{[a-zA-Z0-9_]+\}', '', msg)

    if is_female:
        formatted = re.sub(r'\bhis beard\b', 'her hair', formatted, flags=re.IGNORECASE)
        formatted = re.sub(r'\bhimself\b', 'herself', formatted, flags=re.IGNORECASE)
        formatted = re.sub(r'\bhis\b', 'her', formatted)
        formatted = re.sub(r'\bHis\b', 'Her', formatted)
        formatted = re.sub(r'\bhim\b', 'her', formatted)
        formatted = re.sub(r'\bHim\b', 'Her', formatted)
        formatted = re.sub(r'\bhe\b', 'she', formatted)
        formatted = re.sub(r'\bHe\b', 'She', formatted)

    return formatted


def get_session_leave_message(name: str, event_type: str, session_data: dict = None, target: str = "whatsapp") -> str:
    name = format_player_name(name)
    session_data = session_data or {}
    duration_mins = session_data.get("duration_mins", 1)
    deaths = session_data.get("deaths_count", 0)
    detail = session_data.get("event_detail", {})
    raid_key = detail.get("raid_key") if isinstance(detail, dict) else None

    dynamic_roasts = load_dynamic_roasts()
    roast_group = None
    target_key = event_type
    if event_type == "RAID_CASUALTY":
        specific_key = f"RAID_CASUALTY_{raid_key}" if raid_key else None
        if specific_key and specific_key in MACRO_ROASTS:
            roast_group = MACRO_ROASTS[specific_key]
            target_key = specific_key
        elif specific_key and specific_key in dynamic_roasts:
            roast_group = MACRO_ROASTS.get("RAID_CASUALTY_GENERIC")
            target_key = specific_key
        else:
            roast_group = MACRO_ROASTS.get("RAID_CASUALTY_GENERIC")
            target_key = "RAID_CASUALTY_GENERIC"
    elif event_type in MACRO_ROASTS:
        roast_group = MACRO_ROASTS[event_type]
        target_key = event_type

    candidates = []
    if roast_group and "leave" in roast_group:
        candidates.extend(roast_group["leave"])
    if target_key in dynamic_roasts and "leave" in dynamic_roasts[target_key]:
        candidates.extend(dynamic_roasts[target_key]["leave"])

    if candidates:
        template = random.choice(candidates)
        msg = format_roast_template(
            template,
            name=name,
            duration_mins=duration_mins,
            minutes=duration_mins,
            hours=round(duration_mins / 60, 1),
            deaths=deaths,
            deaths_count=deaths,
            next_death_attempt=max(2, deaths + 1),
            corpse_runs=session_data.get("corpse_runs", 0)
        )
    else:
        msg = get_random_leave_message(name, target)

    if target == "telegram":
        msg = re.sub(r'\*([^*]+)\*', r'<b>\1</b>', msg)
    return msg


def get_session_resume_message(name: str, last_state: dict = None, target: str = "whatsapp") -> str:
    name = format_player_name(name)
    if not last_state:
        return get_random_join_message(name, target)

    event_type = last_state.get("event_type", "PEACEFUL_LOGOUT")
    detail = last_state.get("event_detail", {})
    raid_key = detail.get("raid_key") if isinstance(detail, dict) else None
    duration_mins = last_state.get("duration_mins", 1)
    deaths = last_state.get("deaths_count", 0)

    dynamic_roasts = load_dynamic_roasts()
    roast_group = None
    target_key = event_type
    if event_type == "RAID_CASUALTY":
        specific_key = f"RAID_CASUALTY_{raid_key}" if raid_key else None
        if specific_key and specific_key in MACRO_ROASTS:
            roast_group = MACRO_ROASTS[specific_key]
            target_key = specific_key
        elif specific_key and specific_key in dynamic_roasts:
            roast_group = MACRO_ROASTS.get("RAID_CASUALTY_GENERIC")
            target_key = specific_key
        else:
            roast_group = MACRO_ROASTS.get("RAID_CASUALTY_GENERIC")
            target_key = "RAID_CASUALTY_GENERIC"
    elif event_type in MACRO_ROASTS:
        roast_group = MACRO_ROASTS[event_type]
        target_key = event_type

    candidates = []
    if roast_group and "resume" in roast_group:
        candidates.extend(roast_group["resume"])
    if target_key in dynamic_roasts and "resume" in dynamic_roasts[target_key]:
        candidates.extend(dynamic_roasts[target_key]["resume"])

    if candidates:
        template = random.choice(candidates)
        msg = format_roast_template(
            template,
            name=name,
            duration_mins=duration_mins,
            minutes=duration_mins,
            hours=round(duration_mins / 60, 1),
            deaths=deaths,
            deaths_count=deaths,
            next_death_attempt=max(2, deaths + 1),
            corpse_runs=last_state.get("corpse_runs", 0)
        )
    else:
        return get_random_join_message(name, target)

    if target == "telegram":
        msg = re.sub(r'\*([^*]+)\*', r'<b>\1</b>', msg)
    return msg
