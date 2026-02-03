from flask import Flask, request, render_template,  redirect, jsonify, url_for, session
import sqlite3
import os
print("DB exists:", os.path.exists(DATABASE))
# 1️⃣ Create the Flask app
app = Flask(__name__)
app.secret_key = "your_secret_key"


# --- Database setup ---
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATABASE = os.path.join(BASE_DIR, "Golf.db")


def get_db():
    conn = sqlite3.connect(DATABASE)  # Use the correct variable
    conn.row_factory = sqlite3.Row  # <-- this makes rows behave like dictionaries
    return conn

@app.route("/", methods=["GET", "POST"])
def select_player():
    db = get_db()
    players = db.execute("SELECT * FROM player").fetchall()

    # Convert sqlite3.Row objects to normal dicts
    players = [dict(row) for row in players]

    print("PLAYERS FROM DB (as dicts):", players)

    if request.method == "POST":
        session["player_id"] = request.form.get("player_id")
        return redirect(url_for("dashboard"))

    return render_template("select_player.html", players=players)


@app.route("/dashboard")
def dashboard():
    if "player_id" not in session:
        return redirect(url_for("select_player"))
    
    player_id = session["player_id"]
    db = get_db()
    
    player = db.execute("SELECT player_name, handicap_index FROM player WHERE player_id = ?", (player_id,)).fetchone()
    player = dict(player) if player else {"player_name": "Unknown", "handicap_index": 0}

    # Example stats queries
    stats = {}
    stats["avg_score"] = db.execute(
        "SELECT AVG(total_score) FROM rounds WHERE player_id = ?", (player_id,)
    ).fetchone()[0] or 0
    stats["best_score"] = db.execute(
        "SELECT MIN(total_score) FROM rounds WHERE player_id = ?", (player_id,)
    ).fetchone()[0] or 0
    last_round = db.execute(
        "SELECT total_score, round_id FROM rounds WHERE player_id = ? ORDER BY round_date DESC LIMIT 1",
        (player_id,)
    ).fetchone()

    if last_round:
        stats["last_score"] = last_round["total_score"]
        stats["last_round_id"] = last_round["round_id"]
    else:
        stats["last_score"] = None
        stats["last_round_id"] = None

    return render_template("dashboard.html", player=player, stats=stats)


@app.route("/add_player", methods=["GET", "POST"])
def add_player():
    if request.method == "POST":
        name = request.form.get("player_name")
        handicap = request.form.get("handicap_index")
        db = get_db()
        db.execute("INSERT INTO player (player_name, handicap_index) VALUES (?, ?)", (name,handicap))
        
        db.commit()
        return redirect(url_for("select_player"))

    return render_template("add_player.html")


# --- Step 1: Home page route ---
@app.route("/home")
def home():
    return render_template("home.html")


@app.route("/stats")
def stats():
    player_id = session.get("player_id")
    if not player_id:
        return redirect(url_for("select_player"))

    conn = get_db()
    cur = conn.cursor()

    # Get aggregate stats from all rounds
    cur.execute(
        """
        SELECT 
            COUNT(*) AS rounds_played,
            AVG(r.total_score) AS avg_gross,
            AVG(r.total_score - r.course_handicap) AS avg_net
        FROM rounds r
        where r.player_id = ?
    """, (player_id,))
    
    general_stats = cur.fetchone()
    rounds_played = general_stats["rounds_played"] or 0
    avg_gross = (
        round(general_stats["avg_gross"], 1) if general_stats["avg_gross"] else 0
    )
    avg_net = round(general_stats["avg_net"], 1) if general_stats["avg_net"] else 0

    # Get course ids and names
    cur.execute("SELECT course_id, name FROM courses ORDER BY name")
    courses = [dict(row) for row in cur.fetchall()]

    # Get totals for GIR, FIR, putts
    cur.execute(
        """
        SELECT 
            SUM(s.putts) AS total_putts,
            SUM(s.green_in_reg) AS total_gir,
            SUM(s.FIR) AS total_fir,
            COUNT(*) AS total_holes
        FROM scores s
        LEFT JOIN rounds r ON s.round_id = r.round_id
        where r.player_id = ?
    """, (session["player_id"],))
    
    scores_stats = cur.fetchone()
    total_holes = scores_stats["total_holes"] or 0
    avg_putts = (
        round(scores_stats["total_putts"] / total_holes, 2) if total_holes else 0
    )
    gir_percent = (
        round((scores_stats["total_gir"] / total_holes) * 100, 1) if total_holes else 0
    )
    fir_percent = (
        round((scores_stats["total_fir"] / total_holes) * 100, 1) if total_holes else 0
    )

    # Get score trend per round
    cur.execute(
        """
        SELECT 
            r.round_date,
            r.total_score,
            (r.total_score - r.course_handicap) AS net_score
        FROM rounds r
        where r.player_id = ?
        ORDER BY r.round_date
    """, (session["player_id"],)).fetchone()
        
    

    trend_rows = cur.fetchall()
    trend_data = [dict(row) for row in trend_rows]  # convert each Row to a dict

    conn.close()
    
    if avg_putts <= 1.7:
        putts_rating_label = "Excellent"
        putts_rating_class = "good"
    elif avg_putts <= 2.0:
        putts_rating_label = "Good"
        putts_rating_class = "good"
    elif avg_putts <= 2.3:
        putts_rating_label = "Average"
        putts_rating_class = "avg"
    else:
        putts_rating_label = "Needs Work"
        putts_rating_class = "bad"
    
    return render_template(
        "stats.html",
        rounds_played=rounds_played,
        avg_gross=avg_gross,
        avg_net=avg_net,
        gir_percent=gir_percent,
        fir_percent=fir_percent,
        avg_putts=avg_putts,
        trend_data=trend_data,
        putts_rating_label=putts_rating_label,
        putts_rating_class=putts_rating_class,
        courses=courses,
    )


@app.route("/rounds_history")
def rounds_history():
    player_id = session.get("player_id")
    if not player_id:
        return redirect(url_for("select_player"))

    conn = get_db()
    cur = conn.cursor()

    # Get all rounds with course name, date, gross score, net score
    cur.execute(
        """
        SELECT r.round_id, c.name AS course_name, r.round_date, r.total_score, r.course_handicap,
               (r.total_score - r.course_handicap) AS net_score
        FROM rounds r
        JOIN courses c ON r.course_id = c.course_id
        WHERE r.player_id = ?
        ORDER BY r.round_date DESC
    """, (player_id))
    
    rounds = cur.fetchall()
    conn.close()

    return render_template("rounds_history.html", rounds=rounds)


@app.route("/view_round/<int:round_id>")
def view_round(round_id):
    player_id = session.get("player_id")
    if not player_id:
        return redirect(url_for("select_player"))

    conn = get_db()
    cur = conn.cursor()

    # Get round info
    cur.execute(
        """
        SELECT r.round_id, c.name AS course_name, r.round_date, r.total_score, r.course_handicap,
               (r.total_score - r.course_handicap) AS net_score, r.notes
        FROM rounds r
        JOIN courses c ON r.course_id = c.course_id
        WHERE r.round_id = ? and player_id = ?
    """,
        (round_id,player_id),
    )
    round_info = cur.fetchone()

    if not round_info:
        return "Round not found", 404

    # Get hole-by-hole scores
    cur.execute(
        """
        SELECT hole_number, strokes, putts, FIR, green_in_reg
        FROM scores
        WHERE round_id = ? and player_id = ?
        ORDER BY hole_number
    """, (round_id,player_id,),)
    
    scores = cur.fetchall()
    conn.close()

    return render_template("view_round.html", round=round_info, scores=scores)

def calculate_handicap_index(player_id):
    """
    Calculate a USGA-style handicap index using the best 8 of the last 20 rounds.
    Differential = (total_score - course_rating) * 113 / slope_rating
    """
    conn = get_db()
    cur = conn.cursor()

    # Get last 20 rounds with course rating & slope
    cur.execute("""
        SELECT r.total_score, c.course_rating, c.slope_rating
        FROM rounds r
        JOIN courses c ON r.course_id = c.course_id
        WHERE r.player_id = ?
          AND r.total_score IS NOT NULL
          AND c.course_rating IS NOT NULL
          AND c.slope_rating IS NOT NULL
        ORDER BY r.round_date DESC
        LIMIT 20
    """, (player_id,))

    rounds = cur.fetchall()
    conn.close()

    if len(rounds) < 3:
        return None  # need at least 3 rounds for a valid handicap

    score_differentials = []
    for r in rounds:
        total_score = r["total_score"]
        course_rating = r["course_rating"]
        slope_rating = r["slope_rating"]
        differential = (total_score - course_rating) * 113 / slope_rating
        score_differentials.append(differential)

    # Take best 8 of these
    best_count = min(8, len(score_differentials))
    best_scores = sorted(score_differentials)[:best_count]

    handicap_index = round(sum(best_scores) / len(best_scores), 1)

    return max(handicap_index, 0.0)



@app.route("/log_round", methods=["GET", "POST"])
def log_round():
    conn = get_db()
    cur = conn.cursor()

    # Get courses for dropdown (used for both GET and POST)
    cur.execute("SELECT course_id, name, slope_rating FROM courses ORDER BY name")
    courses = cur.fetchall()

    if request.method == "POST":
        # Get selected course
        course_id = request.form.get("course_id")
        if not course_id:
            conn.close()
            return "Please select a course", 400

        # Fetch course info
        cur.execute(
            "SELECT slope_rating FROM courses WHERE course_id = ?", (course_id,)
        )
        course = cur.fetchone()
        if not course:
            conn.close()
            return "Course not found", 404

        # Ensure player is selected
        player_id = session.get("player_id")
        if not player_id:
            conn.close()
            return redirect(url_for("select_player"))

        # Fetch player's handicap_index
        cur.execute(
            "SELECT handicap_index FROM player WHERE player_id = ?", (player_id,)
        )
        player_row = cur.fetchone()
        if not player_row:
            conn.close()
            return "Player not found", 404

        handicap_index = player_row["handicap_index"] or 0

        # Calculate course handicap safely
        slope_rating = course["slope_rating"] or 113  # default to 113 if None
        course_handicap = round(handicap_index * (slope_rating / 113))

        # Collect form data
        round_date = request.form.get("round_date")
        tees = request.form.get("tees", "")
        weather = request.form.get("weather", "")
        notes = request.form.get("notes", "")

        # Insert new round
        cur.execute(
            """
            INSERT INTO rounds (
                course_id, round_date, tees, weather, notes, course_handicap, player_id
            )
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (course_id, round_date, tees, weather, notes, course_handicap, player_id),
        )
        round_id = cur.lastrowid
        conn.commit()

        # Recalculate player handicap after new round
        new_handicap = calculate_handicap_index(player_id)
        if new_handicap is not None:
            cur.execute(
                "UPDATE player SET handicap_index = ? WHERE player_id = ?",
                (new_handicap, player_id),
            )
            conn.commit()

        conn.close()
        return redirect(url_for("enter_scores", round_id=round_id))

    # GET request
    conn.close()
    return render_template("log_round.html", courses=courses)




# Enter scores for a round
@app.route("/enter_scores/<int:round_id>", methods=["GET", "POST"])
def enter_scores(round_id):
    conn = get_db()
    cur = conn.cursor()

    # Get course handicap
    cur.execute(
        """SELECT course_handicap FROM rounds WHERE round_id = ?""", (round_id,)
    )
    round_info = cur.fetchone()
    course_handicap = round_info[0] if round_info else 0

    # Get course info for this round
    cur.execute("SELECT course_id FROM rounds WHERE round_id=?", (round_id,))
    course = cur.fetchone()
    if not course:
        return "Round not found", 404
    course_id = course[0]

    # Get holes for this course
    cur.execute(
        "SELECT hole_number, par FROM holes WHERE course_id=? ORDER BY hole_number",
        (course_id,),
    )
    holes = cur.fetchall()

    total_strokes = 0
    gross_score = 0
    net_score = 0
    edit_mode = False

    if request.method == "POST":
        for hole in holes:
            hole_number = hole["hole_number"]
            par = hole["par"]
            player_id = session.get("player_id")
            strokes = int(request.form.get(f"strokes_{hole_number}") or 0)
            putts = int(request.form.get(f"putts_{hole_number}") or 0)
            FIR = 1 if request.form.get(f"fir_{hole_number}") else 0

            strokes_to_green = max(strokes - putts, 0)
            max_strokes_to_gir = par - 2
            green_in_reg = 1 if strokes_to_green <= max_strokes_to_gir else 0

            total_strokes += strokes

        # ✅ INSERT MUST BE INSIDE THE LOOP
            if strokes > 0:
                cur.execute(
                    """
                    INSERT INTO scores (
                        round_id,
                        hole_number,
                        strokes,
                        putts,
                        FIR,
                        green_in_reg,
                        player_id
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (round_id, hole_number, strokes, putts, FIR, green_in_reg, player_id),
                )

        gross_score = total_strokes
        net_score = gross_score - course_handicap

        cur.execute(
            """
            UPDATE rounds
            SET total_score = ?
            WHERE round_id = ?
            """,
            (total_strokes, round_id),
        )

        conn.commit()
        conn.close()
        return render_template("scores_saved.html", round_id=round_id)



    conn.close()

    return render_template(
        "scores.html",
        round_id=round_id,
        holes=holes,
        gross_score=gross_score,
        course_handicap=course_handicap,
        net_score=net_score,
        total_strokes=total_strokes,
        edit_mode=False,
    )
@app.route("/edit_round/<int:round_id>", methods=["GET", "POST"])
def edit_round(round_id):
    # Ensure a player is selected
    if "player_id" not in session:
        return redirect(url_for("select_player"))
    player_id = session["player_id"]

    conn = get_db()
    cur = conn.cursor()

    # Get round + course, make sure it belongs to this player
    cur.execute(
        "SELECT course_id, course_handicap, player_id FROM rounds WHERE round_id=?",
        (round_id,),
    )
    round_row = cur.fetchone()
    if not round_row:
        return "Round not found", 404

    if round_row["player_id"] != player_id:
        return "Unauthorized: This round does not belong to the selected player", 403

    course_id = round_row["course_id"]
    course_handicap = round_row["course_handicap"]

    # Get holes for the course
    cur.execute(
        "SELECT hole_number, par FROM holes WHERE course_id=? ORDER BY hole_number",
        (course_id,),
    )
    holes = cur.fetchall()

    # Get existing scores for this round
    cur.execute("SELECT * FROM scores WHERE round_id=?", (round_id,))
    rows = cur.fetchall()

    existing_scores = {}
    for row in rows:
        existing_scores[row["hole_number"]] = {
            "strokes": row["strokes"],
            "putts": row["putts"],
            "FIR": row["FIR"],
            "green_in_reg": row["green_in_reg"],
        }

    if request.method == "POST":
        # Delete old scores for this round
        cur.execute("DELETE FROM scores WHERE round_id=?", (round_id,))

        total_strokes = 0

        for hole in holes:
            hole_number = hole["hole_number"]
            par = hole["par"]

            strokes = int(request.form.get(f"strokes_{hole_number}") or 0)
            putts = int(request.form.get(f"putts_{hole_number}") or 0)
            FIR = 1 if request.form.get(f"fir_{hole_number}") else 0

            strokes_to_green = max(strokes - putts, 0)
            green_in_reg = 1 if strokes_to_green <= (par - 2) else 0

            total_strokes += strokes

            if strokes > 0:
                cur.execute(
                    """
                    INSERT INTO scores (
                        round_id, hole_number, strokes, putts, FIR, green_in_reg
                    )
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (round_id, hole_number, strokes, putts, FIR, green_in_reg),
                )

        # Update total score for the round
        cur.execute(
            "UPDATE rounds SET total_score=? WHERE round_id=?",
            (total_strokes, round_id),
        )
        handicap = calculate_handicap_index(session["player_id"])

        if handicap is not None:
            cur.execute("""
            UPDATE player
            SET handicap_index = ?
            WHERE player_id = ?
        """, (handicap, session["player_id"]))
        conn.commit()

        conn.commit()
        conn.close()
        return redirect(url_for("view_round", round_id=round_id))



    conn.close()

    # Calculate totals for display if editing an existing round
    if existing_scores:
        total_strokes = sum(s["strokes"] for s in existing_scores.values())
        total_putts = sum(s["putts"] for s in existing_scores.values())
        total_gir = sum(s["green_in_reg"] for s in existing_scores.values())
        total_fir = sum(s["FIR"] for s in existing_scores.values())
        num_holes = len(holes)
        gir_percent = round((total_gir / num_holes) * 100, 1)
        fir_percent = round((total_fir / num_holes) * 100, 1)
    else:
        total_strokes = total_putts = gir_percent = fir_percent = 0

    return render_template(
        "scores.html",
        round_id=round_id,
        holes=holes,
        existing_scores=existing_scores,
        edit_mode=True,
        course_handicap=course_handicap,
        total_strokes=total_strokes,
        total_putts=total_putts,
        gir_percent=gir_percent,
        fir_percent=fir_percent,
    )

@app.route("/stats/avg_score_per_hole/<int:course_id>")
def avg_score_per_hole(course_id):
    if "player_id" not in session:
        return redirect(url_for("select_player"))
    player_id = session["player_id"]

    conn = get_db()
    cur = conn.cursor()

    # Get holes and average strokes for this course filtered by player
    cur.execute("""
       SELECT
            h.hole_number,
            h.par,
            ROUND(AVG(s.strokes), 2) AS avg_score
        FROM holes h
        LEFT JOIN scores s
            ON h.hole_number = s.hole_number
            LEFT JOIN rounds r
            ON s.round_id = r.round_id
        WHERE h.course_id = ?
          AND r.course_id = h.course_id
          AND r.player_id = ?
        GROUP BY h.hole_number, h.par
        ORDER BY h.hole_number ASC
    """, (course_id, player_id))

    rows = cur.fetchall()
    conn.close()

    holes = []
    for r in rows:
        holes.append({
            "hole_number": r["hole_number"],
            "par": r["par"],
            "avg_score": float(r["avg_score"]) if r["avg_score"] is not None else 0
        })

    return jsonify(holes)


# Get hole diffculty stats
DATABASE = "golf.db"

def get_hole_difficulty(course_id):
    # Make sure we have a player selected
    from flask import session
    if "player_id" not in session:
        return []  # no player, return empty

    player_id = session["player_id"]

    conn = sqlite3.connect(DATABASE)
    conn.row_factory = sqlite3.Row  # return dict-like rows
    cur = conn.cursor()

    # Get hole difficulty stats for this course AND player
    cur.execute("""
        SELECT
            h.hole_number,
            h.par,
            AVG(s.strokes) AS avg_score,
            AVG(s.strokes - h.par) AS avg_over_under_par
        FROM holes h
        LEFT JOIN scores s
            ON h.hole_number = s.hole_number
            LEFT JOIN rounds r 
            ON r.round_id = s.round_id
        WHERE h.course_id = ?
          AND r.player_id = ?
        GROUP BY h.hole_number, h.par
        ORDER BY avg_over_under_par DESC
    """, (course_id, player_id))

    rows = cur.fetchall()
    conn.close()

    # convert to dicts for Chart.js or template
    holes = []
    for r in rows:
        holes.append({
            "hole_number": r["hole_number"],
            "par": r["par"],
            "avg_score": float(r["avg_score"]) if r["avg_score"] is not None else 0,
            "avg_over_under_par": float(r["avg_over_under_par"]) if r["avg_over_under_par"] is not None else 0
        })

    return holes


@app.route('/hole-difficulty/<int:course_id>')
def hole_difficulty(course_id):
    holes = get_hole_difficulty(course_id)
    return render_template('hole_difficulty.html', holes=holes)

@app.route("/add_course", methods=["GET", "POST"])
def add_course():
    if request.method == "POST":
        name = request.form.get("name")
        location = request.form.get("location")
        par = request.form.get("par")
        holes = request.form.get("holes")
        slope_rating = request.form.get("slope_rating") or None
        course_rating = request.form.get("course_rating") or None

        # Validate required fields
        if not name or not par or not holes:
            return "Name, par, and holes are required", 400

        conn = get_db()
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO courses (name, location, par, holes, slope_rating, course_rating)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (name, location, int(par), int(holes), float(slope_rating) if slope_rating else None, float(course_rating) if course_rating else None))
        conn.commit()
        

         # Get the ID of the newly inserted course
        course_id = cur.lastrowid
        conn.close()

        # Redirect to the add_holes page for this course
        return redirect(url_for("add_holes", course_id=course_id))

    # GET request renders form
    return render_template("add_course.html")

@app.route("/add_holes/<int:course_id>", methods=["GET", "POST"])
def add_holes(course_id):
    conn = get_db()
    cur = conn.cursor()

    # Get course info
    cur.execute("SELECT name, holes FROM courses WHERE course_id = ?", (course_id,))
    course = cur.fetchone()
    if not course:
        conn.close()
        return "Course not found", 404

    num_holes = course["holes"]

    if request.method == "POST":
        # Insert each hole with par and yardage
        for i in range(1, num_holes + 1):
            par = request.form.get(f"par_{i}")
            yardage = request.form.get(f"yardage_{i}")
            if not par or not yardage:
                continue
            cur.execute("""
                INSERT INTO holes (course_id, hole_number, par, yardage)
                VALUES (?, ?, ?, ?)
            """, (course_id, i, int(par), int(yardage)))
        conn.commit()
        conn.close()
        return redirect(url_for("log_round"))

    conn.close()
    return render_template("add_holes.html", course=course, num_holes=num_holes)


    conn.close()
    return render_template("add_holes.html", course=course, num_holes=num_holes)


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)