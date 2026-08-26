"""Seed content — the demo athletes and everything they have said, logged and shared.

``seed.py`` holds the *logic* (create, backdate, vote, bind); this module holds the *data*, so the
seeder stays readable as the content grows. It is loaded by absolute path, the same way ``seed.py``
already loads ``web/services/db.py`` — the test fixture imports ``seed.py`` via
``spec_from_file_location``, which never puts ``db/`` on ``sys.path``, so a plain ``import`` would
fail there while working in the container.

FROZEN, do not change (``presentation/showoff/seed-for-screenshots.py`` depends on both, and
``installation.md`` prints them for reviewers):
  * the five original handles, ``coach_maya`` first
  * ``SEED_PASSWORD`` (lives in ``seed.py``)

Posts are ordered OLDEST FIRST and every ``age_days`` is distinct: ``test_seed.py`` asserts the feed
reads newest-first after backdating, and that no two posts land on the same instant. Comments point
at a post by KEY, not by index — indices are derived below, so inserting a post can never silently
re-point an existing comment at the wrong thread.

Language: the app's audience is Israeli, so most athletes write Hebrew and Coach Maya answers each
person in the language they used. That is deliberate content, not encoding noise.
"""

# ---------------------------------------------------------------------------------------------
# Athletes. (handle, display_name, email) — the handle is what authors posts and receives DMs.
# The first five are the original cold-seed clients and are FROZEN; the rest were added when the
# seed grew to cover the whole app rather than only the forum.
# ---------------------------------------------------------------------------------------------
USERS = [
    ("coach_maya",   "Coach Maya",  "coach.maya@example.com"),
    ("alex_runs",    "Alex",        "alex.runs@example.com"),
    ("sara_lifts",   "Sara",        "sara.lifts@example.com"),
    ("deepa_yoga",   "Deepa",       "deepa.yoga@example.com"),
    ("tom_climbs",   "Tom",         "tom.climbs@example.com"),
    ("yael_tri",     "יעל כהן",      "yael.tri@example.com"),
    ("noa_swims",    "נועה לוי",     "noa.swims@example.com"),
    ("itai_lifts",   "איתי ברק",     "itai.lifts@example.com"),
    ("roni_runs",    "רוני שגב",     "roni.runs@example.com"),
    ("amit_climbs",  "עמית דרור",    "amit.climbs@example.com"),
    ("shani_yoga",   "שני אלון",     "shani.yoga@example.com"),
    ("omer_cross",   "עומר נחום",    "omer.cross@example.com"),
    ("talia_bikes",  "טליה רז",      "talia.bikes@example.com"),
    ("guy_boxing",   "גיא פרץ",      "guy.boxing@example.com"),
    ("daniel_hoops", "דניאל אמסלם",  "daniel.hoops@example.com"),
]

# ---------------------------------------------------------------------------------------------
# Profiles. Shaped exactly as ``routes/profile.validate_profile`` returns: the six always-present
# fields, plus the optional planning inputs. Those optionals are what ``derive_tier`` reads, so the
# spread below is deliberate — every tier is represented, and the Advanced ones carry a
# ``training_program`` so F6's balance analysis actually has something to analyse.
#
#   no equipment / split / program        -> beginner
#   equipment and/or split_preference     -> intermediate
#   training_program                      -> advanced
# ---------------------------------------------------------------------------------------------
PROFILES = {
    # --- advanced: they provide a weekly programme, so the balance analysis runs ---
    "coach_maya": {
        "age": 38, "gender": "female", "height": 168.0, "weight": 61.0,
        "goal": "maintain", "training_frequency": 5,
        "equipment": ["barbell", "dumbbell", "machine", "pullup_bar"],
        "split_preference": "upper_lower",
        # balanced on purpose — the analyser should have nothing to complain about here
        "training_program": {"chest": 12, "back": 12, "shoulders": 8, "biceps": 6, "triceps": 6,
                             "quads": 12, "hamstrings": 10, "glutes": 8, "calves": 6, "core": 8},
    },
    "itai_lifts": {
        "age": 27, "gender": "male", "height": 181.0, "weight": 88.5,
        "goal": "gain", "training_frequency": 5,
        "equipment": ["barbell", "dumbbell", "machine"],
        "split_preference": "push_pull_legs",
        # the classic mirror-muscle imbalance: chest:back is 18:6 = 3.0, far outside 0.67-1.5,
        # so this athlete's action plan should lead with "your pulling volume is behind"
        "training_program": {"chest": 18, "back": 6, "shoulders": 10, "biceps": 8, "triceps": 10,
                             "quads": 9, "hamstrings": 4, "glutes": 3, "calves": 2, "core": 4},
    },
    "sara_lifts": {
        "age": 31, "gender": "female", "height": 165.0, "weight": 63.0,
        "goal": "gain", "training_frequency": 4,
        "equipment": ["barbell", "dumbbell", "kettlebell"],
        "split_preference": "upper_lower",
        # under-trained: 4 sets a week for a whole group is below the analyser's floor of 6
        "training_program": {"chest": 8, "back": 9, "shoulders": 4, "biceps": 4, "triceps": 4,
                             "quads": 10, "hamstrings": 8, "glutes": 9, "calves": 2, "core": 6},
    },
    "omer_cross": {
        "age": 29, "gender": "male", "height": 176.0, "weight": 79.0,
        "goal": "maintain", "training_frequency": 6,
        "equipment": ["barbell", "kettlebell", "bodyweight", "pullup_bar"],
        "split_preference": "full_body",
        "training_program": {"chest": 10, "back": 11, "shoulders": 9, "biceps": 6, "triceps": 7,
                             "quads": 14, "hamstrings": 11, "glutes": 9, "calves": 6, "core": 12},
    },
    # --- intermediate: planning inputs, no programme ---
    "alex_runs": {
        "age": 34, "gender": "male", "height": 179.0, "weight": 72.0,
        "goal": "maintain", "training_frequency": 5,
        "equipment": ["bodyweight", "bands"], "split_preference": "full_body",
    },
    "yael_tri": {
        "age": 26, "gender": "female", "height": 170.0, "weight": 58.0,
        "goal": "maintain", "training_frequency": 6,
        "equipment": ["bodyweight", "dumbbell", "bands"], "split_preference": "full_body",
    },
    "noa_swims": {
        "age": 22, "gender": "female", "height": 173.0, "weight": 62.0,
        "goal": "maintain", "training_frequency": 6,
        "equipment": ["bodyweight", "pullup_bar", "bands"],
    },
    "roni_runs": {
        "age": 41, "gender": "female", "height": 164.0, "weight": 57.5,
        "goal": "lose", "training_frequency": 4,
        "split_preference": "full_body",
    },
    "amit_climbs": {
        "age": 30, "gender": "male", "height": 174.0, "weight": 68.0,
        "goal": "maintain", "training_frequency": 4,
        "equipment": ["bodyweight", "pullup_bar"],
    },
    "talia_bikes": {
        "age": 35, "gender": "female", "height": 167.0, "weight": 60.0,
        "goal": "lose", "training_frequency": 5,
        "equipment": ["bodyweight", "machine"], "split_preference": "no_preference",
    },
    "guy_boxing": {
        "age": 24, "gender": "male", "height": 178.0, "weight": 74.0,
        "goal": "lose", "training_frequency": 5,
        "equipment": ["bodyweight", "bands", "kettlebell"],
    },
    # --- beginner: the six core fields only, which is exactly the point of the tier ---
    "deepa_yoga": {
        "age": 45, "gender": "female", "height": 161.0, "weight": 59.0,
        "goal": "maintain", "training_frequency": 3,
    },
    "tom_climbs": {
        "age": 28, "gender": "male", "height": 183.0, "weight": 76.0,
        "goal": "gain", "training_frequency": 3,
    },
    "shani_yoga": {
        "age": 33, "gender": "female", "height": 169.0, "weight": 64.0,
        "goal": "lose", "training_frequency": 2,
    },
    "daniel_hoops": {
        "age": 20, "gender": "male", "height": 190.0, "weight": 84.0,
        "goal": "gain", "training_frequency": 4,
    },
}

# ---------------------------------------------------------------------------------------------
# Check-in history. One tuple per athlete: how many days back to fill, and the shape of the person.
#
#   days      how far back the log runs (one entry per calendar day, newest = today)
#   base      their typical fatigue floor (1-9); higher = a harder-training, more worn athlete
#   swing     how much a training block moves them across the fortnight
#   sleep     their typical night, in hours
#   hr        typical resting heart rate
#   gaps      days they simply did not log — real people miss days, and the heatmap should show it
#
# The generator lives in seed.py; keeping the *personality* here means a reviewer can see at a
# glance why two athletes' dashboards look different without reading any code.
# ---------------------------------------------------------------------------------------------
HISTORY = {
    "coach_maya":   {"days": 60, "base": 3, "swing": 2, "sleep": 7.6, "hr": 52, "gaps": (11, 29, 44)},
    "alex_runs":    {"days": 60, "base": 4, "swing": 3, "sleep": 6.4, "hr": 49, "gaps": (7, 23)},
    "sara_lifts":   {"days": 60, "base": 4, "swing": 3, "sleep": 7.1, "hr": 58, "gaps": (3, 17, 38, 51)},
    "yael_tri":     {"days": 60, "base": 5, "swing": 3, "sleep": 6.2, "hr": 55, "gaps": (14, 15, 16)},
    "itai_lifts":   {"days": 60, "base": 5, "swing": 2, "sleep": 7.8, "hr": 61, "gaps": (9, 34)},
    "noa_swims":    {"days": 45, "base": 3, "swing": 2, "sleep": 8.1, "hr": 47, "gaps": (5, 22)},
    "roni_runs":    {"days": 45, "base": 4, "swing": 2, "sleep": 6.9, "hr": 60, "gaps": (12, 31)},
    "omer_cross":   {"days": 40, "base": 6, "swing": 2, "sleep": 6.6, "hr": 57, "gaps": (8,)},
    "deepa_yoga":   {"days": 30, "base": 2, "swing": 2, "sleep": 8.3, "hr": 54, "gaps": (6, 19)},
    "tom_climbs":   {"days": 30, "base": 4, "swing": 3, "sleep": 7.0, "hr": 56, "gaps": (2, 21)},
    "amit_climbs":  {"days": 25, "base": 3, "swing": 3, "sleep": 7.4, "hr": 53, "gaps": (10,)},
    "talia_bikes":  {"days": 21, "base": 4, "swing": 2, "sleep": 6.8, "hr": 62, "gaps": (4,)},
    "shani_yoga":   {"days": 14, "base": 2, "swing": 1, "sleep": 8.0, "hr": 59, "gaps": ()},
    "guy_boxing":   {"days": 12, "base": 5, "swing": 3, "sleep": 6.1, "hr": 51, "gaps": (3,)},
    # deliberately short: a brand-new athlete, so a reviewer sees what the app looks like on day one
    "daniel_hoops": {"days": 3,  "base": 3, "swing": 1, "sleep": 7.2, "hr": 50, "gaps": ()},
}

# ---------------------------------------------------------------------------------------------
# Attachment files, all under db/seed_media/. (key -> filename, mime)
# The bytes are real: four screenshots of this app, downscaled, plus a short clip — what athletes
# actually share with each other in a training forum.
# ---------------------------------------------------------------------------------------------
MEDIA = {
    "readiness":  ("readiness-card.jpg",   "image/jpeg"),
    "heatmap":    ("history-heatmap.jpg",  "image/jpeg"),
    "plan":       ("weekly-plan.jpg",      "image/jpeg"),
    "programme":  ("programme-split.jpg",  "image/jpeg"),
    "clip":       ("session-clip.mp4",     "video/mp4"),
}

# ---------------------------------------------------------------------------------------------
# Forum posts, OLDEST FIRST, every age distinct. `key` is referenced by comments/votes/media below.
# The first five entries are the original cold-seed posts, kept word for word.
# ---------------------------------------------------------------------------------------------
POSTS = [
    dict(key="welcome", author="coach_maya", age=58,
         title="Welcome to the readiness forum 👋",
         body="Share how training's going, ask for advice, compare readiness states. Be kind and specific."),
    dict(key="reading", author="coach_maya", age=55,
         title="How to read your readiness state",
         body="Ready = push. Moderate = steady. Rest = recover. It's a guide, not a rule — listen to your body too."),
    dict(key="sleep", author="alex_runs", age=52,
         title="Sleep vs readiness — same for you?",
         body="Every time I drop under 6h sleep my readiness tanks the next day. Curious whether that's universal."),
    dict(key="deload", author="sara_lifts", age=49,
         title="Deload weeks — how often do you take them?",
         body="I've been running hard for 7 weeks straight and my numbers are stalling. Thinking it's deload time."),
    dict(key="mobility", author="deepa_yoga", age=46,
         title="Mobility on rest days — worth it?",
         body="On full-rest days I've started doing 20 min of mobility. My next session always feels smoother."),

    dict(key="heb_intro", author="yael_tri", age=43, media="heatmap",
         title="שלושה שבועות עם האפליקציה — מה שלמדתי",
         body="התחלתי לתעד כל יום ופתאום רואים דפוסים. שבועות של לחץ בעבודה = fatigue גבוה יומיים אחרי. "
              "מצרפת צילום של ה-heatmap שלי, מעניין אם זה נראה דומה אצל אחרים."),
    dict(key="hr_flight", author="alex_runs", age=41,
         title="Does anyone else's readiness lie after a long flight?",
         body="Flew 11h, slept 8, still got Rest two days running. Resting HR was +9. The model saw it before I did."),
    dict(key="heb_return", author="noa_swims", age=38,
         title="חזרה אחרי מחלה — כמה זמן לוקח עד שזה מתייצב?",
         body="הייתי שבועיים בבית עם שפעת. חזרתי לבריכה והאפליקציה מקפיצה אותי בין Rest ל-Moderate כל יום. "
              "מישהו עבר את זה? כמה סבלנות צריך?"),
    dict(key="tiers", author="itai_lifts", age=35, media="programme",
         title="ה-Advanced tier סוף סוף נותן פירוק לפי קבוצות שריר",
         body="הזנתי את התוכנית השבועית שלי ופתאום הוא אומר לי שהגב בפיגור רציני מול החזה. "
              "צדק לגמרי, אני יודע שאני מזניח משיכות. מצרף צילום."),
    dict(key="heb_sleep", author="roni_runs", age=32,
         title="שינה מול דופק מנוחה — מה משפיע יותר?",
         body="אצלי דווקא דופק המנוחה הוא המנבא. לילה גרוע אחד לא עושה כלום, אבל דופק גבוה יומיים ברצף — "
              "תמיד Rest. אצלכם?"),
    dict(key="calories", author="talia_bikes", age=29,
         title="יעד הקלוריות — אתם עוקבים אחריו בפועל?",
         body="המספר שהאפליקציה נותנת די קרוב למה שחישבתי לבד, אבל הוא זז לפי ימי אימון וזה מה שעוזר. "
              "מעניין אם אנשים באמת עוקבים או רק מסתכלים."),
    dict(key="climb_grip", author="amit_climbs", age=27,
         title="אצבעות עייפות זה לא soreness רגיל",
         body="מטפס פעמיים בשבוע ואין שדה ל'אצבעות'. אני מדווח את זה כ-soreness וזה עובד בערך, "
              "אבל אשמח לשמוע איך מטפסים אחרים מתעדים."),
    dict(key="deload_2", author="sara_lifts", age=24,
         title="עשיתי דילוד אחרי 7 שבועות — התוצאה",
         body="שבוע של חצי נפח. חזרתי ל-Ready תוך שלושה ימים אחרי שבועיים תקועה ב-Moderate. "
              "לא מאמינה שחיכיתי כל כך הרבה זמן."),
    dict(key="beginner_q", author="daniel_hoops", age=21,
         title="חדש כאן — כמה ימים צריך לפני שהמספר אומר משהו?",
         body="נרשמתי אתמול ויש לי דיווח אחד. הציון קופץ. כמה ימים לוקח עד שזה מתייצב?"),
    dict(key="heb_maya_answer", author="coach_maya", age=19,
         title="לשאלה שחוזרת: כמה זמן עד שהמספר אמין?",
         body="שבוע נותן כיוון, שבועיים נותנים מגמה. יום בודד הוא מדידה, לא סיפור. "
              "תסתכלו על הקו, לא על הנקודה."),
    dict(key="cross_burnout", author="omer_cross", age=17, media="readiness",
         title="שישה אימונים בשבוע — האפליקציה צדקה ואני לא",
         body="הייתי בטוח שאני בסדר. חמישה ימים ברצף Rest, התעקשתי, וביום השישי נפלתי באמצע אימון. "
              "עכשיו אני מוריד לארבעה ומקשיב."),
    dict(key="rest_streak", author="coach_maya", age=15,
         title="Three weeks of Rest in a row — read this before you panic",
         body="A long Rest run almost always means load, sleep or life stress — not that you're broken. "
              "Look at the trend, not at yesterday."),
    dict(key="boxing_new", author="guy_boxing", age=13,
         title="אגרוף + ריצה — איך לדווח training load?",
         body="ספארינג זה לא אותו דבר כמו ריצה קלה גם אם שניהם שעה. אני מדרג ספארינג גבוה יותר "
              "ונראה שהמודל מסכים איתי."),
    dict(key="yoga_light", author="shani_yoga", age=11,
         title="יומיים בשבוע זה מספיק?",
         body="מתאמנת פעמיים בשבוע יוגה. ה-frequency המומלץ אומר לי שלוש. שוקלת להוסיף."),
    dict(key="heb_plan", author="yael_tri", age=9, media="plan",
         title="התוכנית השבועית שהאפליקציה בנתה לי",
         body="ביקשתי חמישה ימים עם ציוד מינימלי וזה מה שיצא. חילקה נכון בין דחיפה למשיכה. מצרפת."),
    dict(key="swim_clip", author="noa_swims", age=7, media="clip",
         title="חזרתי למים 💦",
         body="אחרי ההפסקה — האימון הראשון שהרגיש נורמלי. הדופק חזר ל-47 והציון קפץ ל-Ready."),
    dict(key="hoops_update", author="daniel_hoops", age=5,
         title="עדכון: שלושה ימים והמספר כבר נראה הגיוני",
         body="תודה על התשובות. עדיין קופץ אבל מתחיל להיראות כמו משהו."),
    dict(key="tom_gain", author="tom_climbs", age=4,
         title="Bulking while climbing — anyone balancing both?",
         body="Trying to add weight without losing grip strength. The calorie target helps, the plan less so."),
    dict(key="community", author="coach_maya", age=2,
         title="Two months in — thank you all 🙏",
         body="This forum has become genuinely useful. Keep posting the boring weeks too; they are the ones "
              "that show the trend."),
    dict(key="heb_last", author="itai_lifts", age=1,
         title="עדכון על הגב — חודש של תיקון",
         body="הכפלתי את נפח המשיכות. היחס עכשיו קרוב ל-1:1 והכתפיים כואבות הרבה פחות. עבד."),
]

# ---------------------------------------------------------------------------------------------
# Comments. `post` is a POST key; the index is derived below, so adding a post can never re-point
# an existing comment. `age` must stay below its post's age — a comment cannot predate its thread.
# ---------------------------------------------------------------------------------------------
COMMENTS = [
    dict(post="welcome",  author="alex_runs",   age=57, body="Love this — thanks for setting it up!"),
    dict(post="welcome",  author="sara_lifts",  age=57, body="Finally a place to compare notes. 🙌"),
    dict(post="sleep",    author="coach_maya",  age=51,
         body="Very common — an under-6h night tanks most people's HRV the next morning."),
    dict(post="sleep",    author="sara_lifts",  age=51,
         body="Same here, especially when training load is already high."),
    dict(post="deload",   author="deepa_yoga",  age=48,
         body="Every 4–6 weeks for me, and sooner if my sleep starts slipping."),
    dict(post="mobility", author="alex_runs",   age=45,
         body="20 minutes of mobility genuinely changes how my next session feels."),

    dict(post="heb_intro", author="coach_maya", age=42,
         body="בדיוק בשביל זה ה-heatmap. שבוע לחוץ נראה שם לפני שהוא מורגש."),
    dict(post="heb_intro", author="roni_runs",  age=42, body="אצלי זה נראה כמעט זהה. מטריף כמה זה עקבי."),
    dict(post="hr_flight", author="noa_swims",  age=40, body="+9 in resting HR is huge. Your body was still on the plane."),
    dict(post="heb_return", author="coach_maya", age=37,
         body="אחרי מחלה זה לוקח בערך 7-10 ימים להתייצב. אל תסתכלי על יום בודד, ואל תמהרי לחזור לנפח מלא."),
    dict(post="heb_return", author="yael_tri",  age=36, body="עברתי את זה בחורף. סבלנות, זה חוזר. באמת."),
    dict(post="tiers",     author="coach_maya", age=34,
         body="יחס 3:1 בין חזה לגב זה קלאסי. תכפיל משיכות לפני שאתה מוסיף עוד דחיפות."),
    dict(post="tiers",     author="omer_cross", age=33, body="גם אצלי. הוספתי חתירות והכתפיים הודו לי."),
    dict(post="heb_sleep", author="alex_runs",  age=31, body="Resting HR is the better signal for me too."),
    dict(post="calories",  author="shani_yoga", age=28, body="אני עוקבת בערך. בימי אימון זה באמת שונה."),
    dict(post="climb_grip", author="tom_climbs", age=26,
         body="Same problem. I log grip fatigue as soreness and it tracks well enough."),
    dict(post="deload_2",  author="coach_maya", age=23, body="זו בדיוק התמונה שאני מנסה לתאר. תודה ששיתפת."),
    dict(post="deload_2",  author="itai_lifts", age=22, body="שכנעת אותי. שבוע הבא אני מוריד נפח."),
    dict(post="beginner_q", author="coach_maya", age=20,
         body="שלושה-ארבעה ימים ואתה מתחיל לראות כיוון. שבוע ומעלה — מגמה."),
    dict(post="cross_burnout", author="coach_maya", age=16,
         body="חמישה ימי Rest ברצף זה לא רעש. שמח שהגעת למסקנה הזאת לבד — היא נשארת ככה."),
    dict(post="cross_burnout", author="guy_boxing", age=16, body="חזק. גם אני לומד את זה עכשיו."),
    dict(post="rest_streak", author="talia_bikes", age=14, body="Needed to read this today, thank you."),
    dict(post="yoga_light", author="coach_maya", age=10,
         body="פעמיים זה בסיס טוב. שלוש ייתן לך יותר עקביות בציון, בלי קפיצה בעומס."),
    dict(post="heb_plan",  author="itai_lifts", age=8, body="חלוקה יפה. גם בלי ציוד זה נראה שמיש."),
    dict(post="swim_clip", author="coach_maya", age=6, body="47! חזרת. תעלי נפח לאט השבוע 💪"),
    dict(post="swim_clip", author="yael_tri",   age=6, body="איזה כיף לראות. מגיע לך."),
    dict(post="tom_gain",  author="amit_climbs", age=3, body="Same boat. Grip goes first for me when I eat more."),
    dict(post="community", author="deepa_yoga", age=1, body="Thank you for keeping it kind here. 🙏"),
]

# (post_key, voter) — likes, so the feed isn't a flat wall of zero-score posts.
POST_VOTES = [
    ("welcome", "alex_runs"), ("welcome", "sara_lifts"), ("welcome", "deepa_yoga"), ("welcome", "tom_climbs"),
    ("sleep", "coach_maya"), ("sleep", "sara_lifts"),
    ("deload", "alex_runs"), ("deload", "tom_climbs"),
    ("mobility", "coach_maya"),
    ("heb_intro", "coach_maya"), ("heb_intro", "roni_runs"), ("heb_intro", "noa_swims"), ("heb_intro", "talia_bikes"),
    ("hr_flight", "yael_tri"), ("hr_flight", "noa_swims"),
    ("heb_return", "coach_maya"), ("heb_return", "yael_tri"), ("heb_return", "shani_yoga"),
    ("tiers", "coach_maya"), ("tiers", "omer_cross"), ("tiers", "sara_lifts"), ("tiers", "guy_boxing"),
    ("heb_sleep", "alex_runs"), ("heb_sleep", "amit_climbs"),
    ("calories", "shani_yoga"), ("calories", "roni_runs"),
    ("deload_2", "coach_maya"), ("deload_2", "itai_lifts"), ("deload_2", "yael_tri"),
    ("heb_maya_answer", "daniel_hoops"), ("heb_maya_answer", "noa_swims"), ("heb_maya_answer", "guy_boxing"),
    ("cross_burnout", "coach_maya"), ("cross_burnout", "itai_lifts"), ("cross_burnout", "talia_bikes"),
    ("rest_streak", "talia_bikes"), ("rest_streak", "shani_yoga"), ("rest_streak", "roni_runs"),
    ("heb_plan", "itai_lifts"), ("heb_plan", "omer_cross"),
    ("swim_clip", "coach_maya"), ("swim_clip", "yael_tri"), ("swim_clip", "roni_runs"), ("swim_clip", "talia_bikes"),
    ("community", "deepa_yoga"), ("community", "alex_runs"), ("community", "sara_lifts"), ("community", "yael_tri"),
    ("heb_last", "coach_maya"), ("heb_last", "sara_lifts"),
]

# (index into COMMENTS, voter)
COMMENT_VOTES = [
    (0, "coach_maya"),
    (2, "alex_runs"), (2, "yael_tri"),
    (9, "noa_swims"), (9, "yael_tri"),
    (11, "itai_lifts"), (11, "omer_cross"),
    (16, "sara_lifts"),
    (19, "omer_cross"),
    (24, "noa_swims"),
]

# ---------------------------------------------------------------------------------------------
# Direct messages. (participant_a, participant_b, [(sender, body, age_days, media_key_or_None)])
# Threads read oldest-first. These are the conversations a coach actually has — a question, a
# measurement, advice, and a follow-up days later that closes the loop.
# ---------------------------------------------------------------------------------------------
DM_THREADS = [
    ("yael_tri", "coach_maya", [
        ("yael_tri",   "מאיה, יש לי מרוץ בעוד שבועיים והאפליקציה נותנת לי Moderate כבר ארבעה ימים. "
                       "להתעקש על האימון הקשה או לוותר?", 12, None),
        ("coach_maya", "ארבעה ימים Moderate זה לא אזהרה, זה גוף שעובד. מה השינה שלך אומרת?", 12, None),
        ("yael_tri",   "6.2 בממוצע. לא נהדר.", 12, None),
        ("coach_maya", "זה הסיפור. תעלי לשבע וחצי שלושה לילות ותראי מה קורה — אל תשני את האימון עדיין.", 11, None),
        ("yael_tri",   "סגור. אעדכן ביום ראשון 🙏", 11, None),
        ("yael_tri",   "Ready! 😄 ישנתי 7:40 ממוצע. אתמול היה האימון הכי טוב שלי החודש.", 8, "readiness"),
        ("coach_maya", "בדיוק. עכשיו תשמרי על זה עד המרוץ ואל תוסיפי נפח.", 8, None),
    ]),
    ("itai_lifts", "coach_maya", [
        ("itai_lifts", "ראית את הניתוח שלי? חזה 18 גב 6. זה באמת כזה גרוע?", 20, None),
        ("coach_maya", "כן. זה יחס 3:1, וזה בדרך כלל נגמר בכתפיים. תכפיל משיכות לפני שאתה מוסיף עוד ספסל.", 20, None),
        ("itai_lifts", "אין לי מקום בתוכנית ליותר.", 19, None),
        ("coach_maya", "אז תוריד סטים מחזה. אתה לא צריך 18.", 19, None),
        ("itai_lifts", "חודש אחרי — היחס כמעט 1:1 והכתפיים שקטות. תודה.", 1, "programme"),
    ]),
    ("noa_swims", "coach_maya", [
        ("noa_swims",  "חזרתי אחרי שבועיים מחלה וכל יום זה משהו אחר. זה נורמלי?", 15, None),
        ("coach_maya", "לגמרי. תני לזה 7-10 ימים ואל תסתכלי על יום בודד.", 15, None),
        ("noa_swims",  "והאימונים? נפח מלא?", 14, None),
        ("coach_maya", "חצי נפח שבוע, ואז תעלי לפי איך שאת מרגישה — לא לפי הלוח.", 14, None),
        ("noa_swims",  "עבד. הדופק חזר ל-47 היום 💦", 7, "clip"),
    ]),
    ("alex_runs", "coach_maya", [
        ("alex_runs",  "Flew back from a conference, slept 8 hours, still Rest. Is the model wrong?", 40, None),
        ("coach_maya", "Your resting HR was +9. The model isn't wrong, it just saw it before you did.", 40, None),
        ("alex_runs",  "Fair. How long does that usually take to clear?", 39, None),
        ("coach_maya", "Two or three days for most people. Travel is a load like any other.", 39, None),
    ]),
    ("sara_lifts", "itai_lifts", [
        ("sara_lifts", "עשית דילוד בסוף?", 22, None),
        ("itai_lifts", "עוד לא. אתה?", 22, None),
        ("sara_lifts", "שבוע של חצי נפח וחזרתי ל-Ready תוך שלושה ימים.", 21, "heatmap"),
        ("itai_lifts", "טוב, שכנעת אותי.", 21, None),
    ]),
    ("daniel_hoops", "coach_maya", [
        ("daniel_hoops", "היי, נרשמתי אתמול. כמה זמן עד שהמספר אומר משהו אמיתי?", 4, None),
        ("coach_maya",   "שלושה-ארבעה ימים לכיוון, שבוע למגמה. תדווח כל יום גם כשמשעמם.", 4, None),
        ("daniel_hoops", "מגניב, תודה!", 3, None),
    ]),
    ("talia_bikes", "roni_runs", [
        ("talia_bikes", "את עוקבת אחרי יעד הקלוריות בפועל?", 9, None),
        ("roni_runs",   "בערך. בימי אימון כן, בסופ״ש פחות 😅", 9, None),
        ("talia_bikes", "אותו דבר. לפחות המספר זז לפי העומס.", 8, None),
    ]),
]

# ---------------------------------------------------------------------------------------------
# Derived indices. Comments and votes above name a post by KEY; the exported tuples carry the
# INDEX, because that is the shape seed.py and the existing tests already speak.
# ---------------------------------------------------------------------------------------------
_POST_INDEX = {post["key"]: i for i, post in enumerate(POSTS)}

# (author, title, body, age_days) — the shape SEED_POSTS has always had.
SEED_POSTS = [(p["author"], p["title"], p["body"], p["age"]) for p in POSTS]

# (post_index, author, body, age_days)
SEED_COMMENTS = [(_POST_INDEX[c["post"]], c["author"], c["body"], c["age"]) for c in COMMENTS]

# (post_index, voter_handle)
SEED_POST_VOTES = [(_POST_INDEX[key], voter) for key, voter in POST_VOTES]

# (comment_index, voter_handle)
SEED_COMMENT_VOTES = list(COMMENT_VOTES)

# (post_index, media_key) for posts that carry an attachment
POST_MEDIA = [(_POST_INDEX[p["key"]], p["media"]) for p in POSTS if p.get("media")]

# ---------------------------------------------------------------------------------------------
# Daily calorie target per athlete, in kcal.
#
# NOT a second copy of the formula: each number below was produced by running this profile through
# ``ai/calories.py::daily_calorie_target`` — the app's own Mifflin-St Jeor + activity-factor + goal
# adjustment — and pasting the result. The seed runs in the ``web`` container, which cannot import
# anything from ``ai/``, and re-implementing the arithmetic here is exactly the kind of duplicate
# that drifts. Activity level is read off training_frequency the way a coach would: <=1 sedentary,
# <=2 light, <=4 moderate, else active.
#
# Regenerate after changing any profile:
#   python -c "import importlib.util as u; s=u.spec_from_file_location('c','ai/calories.py'); \
#              m=u.module_from_spec(s); s.loader.exec_module(m); print(m.daily_calorie_target(...))"
CALORIES = {
    "coach_maya": 2258, "itai_lifts": 3754, "sara_lifts": 2585, "omer_cross": 3019,
    "alex_runs": 2887, "yael_tri": 2331, "noa_swims": 2467, "roni_runs": 1413,
    "amit_climbs": 2515, "talia_bikes": 1756, "guy_boxing": 2497, "deepa_yoga": 1876,
    "tom_climbs": 3242, "shani_yoga": 1384, "daniel_hoops": 3495,
}

# What the recommendation engine says for each readiness state. Copied from the wording the live
# engine produces, so a seeded history reads exactly like a real one.
RECOMMENDATIONS = {
    "Ready":    ["Readiness is high; continue with the planned session using normal progression."],
    "Moderate": ["Readiness is moderate; use a controlled session and adjust if symptoms worsen."],
    "Rest":     ["Readiness is low; prioritise recovery and keep today easy or off."],
}
