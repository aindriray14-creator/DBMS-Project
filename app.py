from flask import Flask, render_template, request, redirect, url_for, flash
import oracledb
from datetime import datetime

app = Flask(__name__)
app.secret_key = "college_events_secret"

DB_USER = "system"
DB_PASSWORD = "dbms123"
DB_DSN = "localhost:1521/XE"


def get_conn():
    return oracledb.connect(user=DB_USER, password=DB_PASSWORD, dsn=DB_DSN)


def query(sql, params=None):
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute(sql, params or [])
        return cur.fetchall()


def run(sql, params=None):
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute(sql, params or [])
        conn.commit()


def call_proc(name, args):
    with get_conn() as conn:
        cur = conn.cursor()
        cur.callproc(name, args)


def to_date(text):
    return datetime.strptime(text, "%Y-%m-%d")


def form_page(title, fields, action, success_msg):
    if request.method == "POST":
        try:
            action(request.form)
            flash(success_msg, "ok")
            return redirect(url_for("index"))
        except oracledb.DatabaseError as e:
            flash(str(e).split("\n")[0], "error")
        except ValueError:
            flash("Please check the values you entered.", "error")
    return render_template("form.html", title=title, fields=fields)


# ---------- Home: list of events ----------
@app.route("/")
def index():
    events = query("""
        SELECT E.Event_ID, E.Event_Name, C.Club_Name,
               NVL(V.Venue_Name, 'Not allocated'),
               TO_CHAR(E.Start_Date, 'DD-Mon-YYYY'),
               TO_CHAR(E.End_Date, 'DD-Mon-YYYY'),
               E.Status
        FROM EVENT E
        JOIN CLUB C ON E.Club_ID = C.Club_ID
        LEFT JOIN VENUE V ON E.Venue_ID = V.Venue_ID
        ORDER BY E.Event_ID
    """)
    return render_template("index.html", events=events)


# ---------- Add event ----------
@app.route("/add_event", methods=["GET", "POST"])
def add_event():
    fields = [
        {"name": "club_id", "label": "Club", "type": "select",
         "options": query("SELECT Club_ID, Club_Name FROM CLUB ORDER BY Club_Name")},
        {"name": "event_name", "label": "Event name", "type": "text"},
        {"name": "event_type", "label": "Event type", "type": "text"},
        {"name": "start_date", "label": "Start date", "type": "date"},
        {"name": "end_date", "label": "End date", "type": "date"},
    ]

    def action(f):
        run("""INSERT INTO EVENT (Event_ID, Club_ID, Event_Name, Event_Type, Start_Date, End_Date)
               VALUES ((SELECT NVL(MAX(Event_ID), 0) + 1 FROM EVENT), :1, :2, :3, :4, :5)""",
            [int(f["club_id"]), f["event_name"], f["event_type"],
             to_date(f["start_date"]), to_date(f["end_date"])])

    return form_page("Add Event", fields, action, "Event created.")


# ---------- Allocate venue (calls ALLOCATE_VENUE) ----------
@app.route("/allocate_venue", methods=["GET", "POST"])
def allocate_venue():
    fields = [
        {"name": "event_id", "label": "Event", "type": "select",
         "options": query("SELECT Event_ID, Event_Name FROM EVENT WHERE Status <> 'Cancelled' ORDER BY Event_ID")},
        {"name": "venue_id", "label": "Venue (available only)", "type": "select",
         "options": query("SELECT Venue_ID, Venue_Name || ' (capacity ' || Capacity || ')' FROM VENUE WHERE Status = 'Available' ORDER BY Venue_ID")},
    ]

    def action(f):
        call_proc("ALLOCATE_VENUE", [int(f["event_id"]), int(f["venue_id"])])

    return form_page("Allocate Venue", fields, action, "Venue allocated.")


# ---------- Assign volunteer (calls ASSIGN_VOLUNTEER) ----------
@app.route("/assign_volunteer", methods=["GET", "POST"])
def assign_volunteer():
    fields = [
        {"name": "event_id", "label": "Event", "type": "select",
         "options": query("SELECT Event_ID, Event_Name FROM EVENT ORDER BY Event_ID")},
        {"name": "student_id", "label": "Student", "type": "select",
         "options": query("SELECT Student_ID, Student_Name || ' (' || Department || ')' FROM STUDENT ORDER BY Student_Name")},
        {"name": "role", "label": "Role", "type": "text"},
    ]

    def action(f):
        call_proc("ASSIGN_VOLUNTEER", [int(f["event_id"]), int(f["student_id"]), f["role"]])

    return form_page("Assign Volunteer", fields, action, "Volunteer assigned.")


# ---------- Add expense ----------
@app.route("/add_expense", methods=["GET", "POST"])
def add_expense():
    fields = [
        {"name": "event_id", "label": "Event", "type": "select",
         "options": query("SELECT Event_ID, Event_Name FROM EVENT ORDER BY Event_ID")},
        {"name": "expense_type", "label": "Expense type", "type": "text"},
        {"name": "amount", "label": "Amount", "type": "number"},
        {"name": "expense_date", "label": "Date", "type": "date"},
    ]

    def action(f):
        run("""INSERT INTO EXPENSE (Expense_ID, Event_ID, Expense_Type, Amount, Expense_Date)
               VALUES ((SELECT NVL(MAX(Expense_ID), 0) + 1 FROM EXPENSE), :1, :2, :3, :4)""",
            [int(f["event_id"]), f["expense_type"], float(f["amount"]), to_date(f["expense_date"])])

    return form_page("Add Expense", fields, action, "Expense recorded.")


# ---------- Add sponsorship ----------
@app.route("/add_sponsorship", methods=["GET", "POST"])
def add_sponsorship():
    fields = [
        {"name": "event_id", "label": "Event", "type": "select",
         "options": query("SELECT Event_ID, Event_Name FROM EVENT ORDER BY Event_ID")},
        {"name": "sponsor", "label": "Sponsor name", "type": "text"},
        {"name": "amount", "label": "Amount", "type": "number"},
        {"name": "status", "label": "Payment status", "type": "select",
         "options": [("Pending", "Pending"), ("Paid", "Paid")]},
    ]

    def action(f):
        run("""INSERT INTO SPONSORSHIP (Sponsorship_ID, Event_ID, Sponsor_Name, Amount, Payment_Status)
               VALUES ((SELECT NVL(MAX(Sponsorship_ID), 0) + 1 FROM SPONSORSHIP), :1, :2, :3, :4)""",
            [int(f["event_id"]), f["sponsor"], float(f["amount"]), f["status"]])

    return form_page("Add Sponsorship", fields, action, "Sponsorship recorded.")


# ---------- Financial summary (uses the two functions) ----------
@app.route("/summary")
def summary():
    rows = query("""
        SELECT E.Event_Name, E.Status,
               CALCULATE_TOTAL_SPONSORSHIP(E.Event_ID),
               CALCULATE_EVENT_EXPENSE(E.Event_ID)
        FROM EVENT E ORDER BY E.Event_ID
    """)
    return render_template("summary.html", rows=rows)


# ---------- Volunteers list ----------
@app.route("/volunteers")
def volunteers():
    rows = query("""
        SELECT E.Event_Name, S.Student_Name, S.Department, VO.Role, VO.Status
        FROM VOLUNTEER VO
        JOIN EVENT E ON VO.Event_ID = E.Event_ID
        JOIN STUDENT S ON VO.Student_ID = S.Student_ID
        ORDER BY E.Event_ID, S.Student_Name
    """)
    return render_template("volunteers.html", rows=rows)

# ---------- Update event status (including Cancel) ----------
@app.route("/update_status/<int:event_id>", methods=["POST"])
def update_status(event_id):
    new_status = request.form["status"]
    try:
        with get_conn() as conn:
            cur = conn.cursor()
            cur.execute("SELECT Venue_ID FROM EVENT WHERE Event_ID = :1", [event_id])
            row = cur.fetchone()
            venue_id = row[0] if row else None

            if new_status == "Cancelled":
                cur.execute("UPDATE EVENT SET Status = 'Cancelled', Venue_ID = NULL WHERE Event_ID = :1",
                            [event_id])
                if venue_id:
                    cur.execute("""UPDATE VENUE SET Status = 'Available'
                                   WHERE Venue_ID = :v1
                                   AND NOT EXISTS (SELECT 1 FROM EVENT
                                                   WHERE Venue_ID = :v2 AND Status <> 'Cancelled')""",
                                {"v1": venue_id, "v2": venue_id})
            else:
                cur.execute("UPDATE EVENT SET Status = :1 WHERE Event_ID = :2", [new_status, event_id])
            conn.commit()
        flash("Event status updated.", "ok")
    except oracledb.DatabaseError as e:
        flash(str(e).split("\n")[0], "error")
    return redirect(url_for("index"))


# ---------- Delete event ----------
@app.route("/delete_event/<int:event_id>", methods=["POST"])
def delete_event(event_id):
    try:
        with get_conn() as conn:
            cur = conn.cursor()
            cur.execute("SELECT Venue_ID FROM EVENT WHERE Event_ID = :1", [event_id])
            row = cur.fetchone()
            venue_id = row[0] if row else None

            for table in ("VOLUNTEER", "EQUIPMENT", "SPONSORSHIP", "EXPENSE"):
                cur.execute("DELETE FROM " + table + " WHERE Event_ID = :1", [event_id])
            cur.execute("DELETE FROM EVENT WHERE Event_ID = :1", [event_id])

            if venue_id:
                cur.execute("""UPDATE VENUE SET Status = 'Available'
                               WHERE Venue_ID = :v1
                               AND NOT EXISTS (SELECT 1 FROM EVENT
                                               WHERE Venue_ID = :v2 AND Status <> 'Cancelled')""",
                            {"v1": venue_id, "v2": venue_id})
            conn.commit()
        flash("Event deleted.", "ok")
    except oracledb.DatabaseError as e:
        flash(str(e).split("\n")[0], "error")
    return redirect(url_for("index"))

if __name__ == "__main__":
    app.run(debug=True)