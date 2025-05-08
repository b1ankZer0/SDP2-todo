import tkinter as tk
from tkinter import ttk, messagebox, simpledialog
import tkcalendar as cal
import sqlite3
import hashlib
import os
import datetime
from functools import partial

class Database:
    def __init__(self):
        # Create database if it doesn't exist
        self.conn = sqlite3.connect('todo_app.db')
        self.cursor = self.conn.cursor()
        
        # Create tables if they don't exist
        self.cursor.execute('''
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL
        )
        ''')
        
        self.cursor.execute('''
        CREATE TABLE IF NOT EXISTS todos (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            date TEXT NOT NULL,
            title TEXT NOT NULL,
            description TEXT,
            status TEXT DEFAULT 'pending',
            due_time TEXT DEFAULT NULL,
            completed_date TEXT DEFAULT NULL,
            priority TEXT DEFAULT 'medium',
            FOREIGN KEY (user_id) REFERENCES users (id)
        )
        ''')
        
        # Check if we need to alter the existing todos table to add new columns
        try:
            self.cursor.execute("SELECT status, due_time, completed_date, priority FROM todos LIMIT 1")
        except sqlite3.OperationalError:
            # Need to add new columns
            try:
                self.cursor.execute("ALTER TABLE todos ADD COLUMN status TEXT DEFAULT 'pending'")
                self.cursor.execute("ALTER TABLE todos ADD COLUMN due_time TEXT DEFAULT NULL")
                self.cursor.execute("ALTER TABLE todos ADD COLUMN completed_date TEXT DEFAULT NULL")
                self.cursor.execute("ALTER TABLE todos ADD COLUMN priority TEXT DEFAULT 'medium'")
                self.conn.commit()
            except sqlite3.OperationalError:
                pass  # Column may already exist

        try:
            self.cursor.execute("SELECT priority FROM todos LIMIT 1")
        except sqlite3.OperationalError:
            # Need to add priority column
            try:
                self.cursor.execute("ALTER TABLE todos ADD COLUMN priority TEXT DEFAULT 'medium'")
                self.conn.commit()
                print("Added missing priority column to the todos table")
            except sqlite3.OperationalError:
                pass  # Column may already exist
                
        self.conn.commit()
    
    def close(self):
        self.conn.close()
        
    def hash_password(self, password):
        """Hash a password for storing."""
        salt = os.urandom(32)  # A new salt for this user
        key = hashlib.pbkdf2_hmac(
            'sha256',  # Hash algorithm
            password.encode('utf-8'),  # Convert password to bytes
            salt,  # Salt
            100000,  # Number of iterations
        )
        # Store salt and key
        return salt + key
    
    def verify_password(self, stored_password, provided_password):
        """Verify a stored password against one provided by user"""
        salt = stored_password[:32]  # 32 is the length of salt
        stored_key = stored_password[32:]
        key = hashlib.pbkdf2_hmac(
            'sha256',
            provided_password.encode('utf-8'),
            salt,
            100000
        )
        return key == stored_key

    def register_user(self, username, password):
        try:
            password_hash = self.hash_password(password)
            self.cursor.execute("INSERT INTO users (username, password_hash) VALUES (?, ?)", 
                               (username, password_hash))
            self.conn.commit()
            return True
        except sqlite3.IntegrityError:
            # Username already exists
            return False
    
    def authenticate_user(self, username, password):
        self.cursor.execute("SELECT id, password_hash FROM users WHERE username = ?", (username,))
        result = self.cursor.fetchone()
        
        if result:
            user_id, stored_password = result
            # Convert stored_password from binary to bytes if needed
            if isinstance(stored_password, str):
                stored_password = bytes.fromhex(stored_password)
            
            if self.verify_password(stored_password, password):
                return user_id
        return None
    
    # Modified: Added due_time parameter
    def add_todo(self, user_id, date, title, description="", due_time=None, priority="medium"):
        self.cursor.execute(
            "INSERT INTO todos (user_id, date, title, description, due_time, priority) VALUES (?, ?, ?, ?, ?, ?)",
            (user_id, date, title, description, due_time, priority)
        )
        self.conn.commit()
        return self.cursor.lastrowid
    
    # Modified: Include status in fetched todos
    def get_todos_by_date(self, user_id, date):
        self.cursor.execute(
            "SELECT id, date, title, description, status, due_time, priority FROM todos WHERE user_id = ? AND date = ? ORDER BY CASE priority WHEN 'high' THEN 1 WHEN 'medium' THEN 2 WHEN 'low' THEN 3 END, id DESC",
            (user_id, date)
        )
        return self.cursor.fetchall()
    
    # Modified: Include status in search results
    def search_todos(self):
        keyword = self.search_entry.get().strip()
        if not keyword:
            messagebox.showinfo("Info", "Please enter a search keyword")
            return
            
        # Store the search keyword for possible reuse after deletion
        self.last_search_keyword = keyword
        self.in_search_mode = True  # Flag to indicate we're viewing search results
            
        # Clear existing items
        for item in self.tree.get_children():
            self.tree.delete(item)
            
        # Search todos
        todos = self.db.search_todos(self.user_id, keyword)
        if not todos:
            messagebox.showinfo("Search Results", "No todos found matching your search")
            return
            
        # Sort todos by date (most recent first)
        todos = sorted(todos, key=lambda x: x[1], reverse=True)
            
        # Current date and time for checking overdue
        now = datetime.datetime.now()
        current_date = now.strftime("%Y-%m-%d")
        current_time = now.strftime("%H:%M")
        
        # Display results
        for todo in todos:
            todo_id, date, title, description, status, due_time, priority = todo
            
            # Determine if task is overdue
            tag = status
            if status == 'pending' and (date < current_date or 
                                    (date == current_date and due_time and due_time < current_time)):
                tag = 'overdue'
                
            self.tree.insert("", "end", 
                        values=(todo_id, date, title, description, status, due_time or "", priority), 
                        tags=(tag, priority))

    # New: Method to get all todos sorted by priority
    def get_todos_by_priority(self, user_id):
        self.cursor.execute(
            """SELECT id, date, title, description, status, due_time, priority 
            FROM todos 
            WHERE user_id = ? AND status = 'pending'
            ORDER BY CASE priority 
                WHEN 'high' THEN 1 
                WHEN 'medium' THEN 2 
                WHEN 'low' THEN 3 
            END, date ASC, due_time ASC""",  # Sort by priority, then date, then due time
            (user_id,)
        )
        return self.cursor.fetchall()
    
    # Modified: Update function to include due_time
    def update_todo(self, todo_id, title, description, due_time=None, priority=None):
        query = "UPDATE todos SET title = ?, description = ?"
        params = [title, description]
        
        if due_time is not None:
            query += ", due_time = ?"
            params.append(due_time)
        
        if priority is not None:
            query += ", priority = ?"
            params.append(priority)
            
        query += " WHERE id = ?"
        params.append(todo_id)
        
        self.cursor.execute(query, params)
        self.conn.commit()
        return self.cursor.rowcount > 0
    
    def delete_todo(self, todo_id):
        self.cursor.execute("DELETE FROM todos WHERE id = ?", (todo_id,))
        self.conn.commit()
        return self.cursor.rowcount > 0
    
    # New: Mark a todo as done
    def mark_todo_as_done(self, todo_id):
        completed_date = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        self.cursor.execute("UPDATE todos SET status = 'completed', completed_date = ? WHERE id = ?", 
                          (completed_date, todo_id))
        self.conn.commit()
        return self.cursor.rowcount > 0
    
    # New: Mark a todo as pending (undone)
    def mark_todo_as_pending(self, todo_id):
        self.cursor.execute("UPDATE todos SET status = 'pending', completed_date = NULL WHERE id = ?", 
                          (todo_id,))
        self.conn.commit()
        return self.cursor.rowcount > 0
    
    # New: Get statistics for todos
    def get_todo_stats(self, user_id):
        # Get count of completed todos
        self.cursor.execute("SELECT COUNT(*) FROM todos WHERE user_id = ? AND status = 'completed'", 
                          (user_id,))
        completed_count = self.cursor.fetchone()[0]
        
        # Get count of pending todos
        self.cursor.execute("SELECT COUNT(*) FROM todos WHERE user_id = ? AND status = 'pending'", 
                          (user_id,))
        pending_count = self.cursor.fetchone()[0]
        
        # Get count of overdue todos (pending todos with due date in the past)
        current_date = datetime.datetime.now().strftime("%Y-%m-%d")
        current_time = datetime.datetime.now().strftime("%H:%M")
        
        self.cursor.execute("""
        SELECT COUNT(*) FROM todos 
        WHERE user_id = ? AND status = 'pending' 
        AND (date < ? OR (date = ? AND due_time < ? AND due_time IS NOT NULL))
        """, (user_id, current_date, current_date, current_time))
        
        overdue_count = self.cursor.fetchone()[0]
        
        return {
            'completed': completed_count,
            'pending': pending_count,
            'overdue': overdue_count
        }

class LoginFrame(tk.Frame):
    def __init__(self, parent, db, show_main_app):
        super().__init__(parent, bg="#f7f9f9")
        self.db = db
        self.show_main_app = show_main_app
        
        # Modified: Make the login frame similar to the image
        self.pack(fill="both", expand=True)
        
        # Create a white card in the center
        self.card_frame = tk.Frame(self, bg="white", padx=20, pady=20,
                                  highlightbackground="#e0e0e0", 
                                  highlightthickness=1)
        self.card_frame.place(relx=0.5, rely=0.5, anchor="center", width=350, height=350)
        
        # Add drop shadow effect (simulated with additional frames)
        shadow_frame = tk.Frame(self, bg="#e0e0e0")
        shadow_frame.place(relx=0.502, rely=0.502, anchor="center", width=350, height=350)
        
        # Place card on top of shadow
        self.card_frame.lift()
        
        self.create_widgets()
        
    def create_widgets(self):
        # Title
        tk.Label(self.card_frame, text="Todo App", font=("Arial", 18, "bold"), bg="white").pack(pady=(0, 20))
        
        # Username
        tk.Label(self.card_frame, text="Username:", anchor="w", bg="white").pack(fill="x")
        self.username_entry = tk.Entry(self.card_frame, font=("Arial", 12))
        self.username_entry.pack(fill="x", pady=(0, 15), ipady=5)
        
        # Password
        tk.Label(self.card_frame, text="Password:", anchor="w", bg="white").pack(fill="x")
        self.password_entry = tk.Entry(self.card_frame, show="*", font=("Arial", 12))
        self.password_entry.pack(fill="x", pady=(0, 25), ipady=5)
        
        # Login button
        login_btn = tk.Button(self.card_frame, text="Login", command=self.login, 
                             bg="#4CAF50", fg="white", font=("Arial", 12), 
                             relief="flat", cursor="hand2")
        login_btn.pack(fill="x", pady=(0, 10), ipady=5)
        
        # Register button
        register_btn = tk.Button(self.card_frame, text="Register", command=self.register, 
                                bg="#4CAF50", fg="white", font=("Arial", 12),
                                relief="flat", cursor="hand2")
        register_btn.pack(fill="x", ipady=5)
        
    def login(self):
        username = self.username_entry.get().strip()
        password = self.password_entry.get()
        
        if not username or not password:
            messagebox.showerror("Error", "Username and password are required.")
            return
            
        user_id = self.db.authenticate_user(username, password)
        if user_id:
            self.show_main_app(user_id, username)
        else:
            messagebox.showerror("Login Failed", "Invalid username or password.")
            
    def register(self):
        username = self.username_entry.get().strip()
        password = self.password_entry.get()
        
        if not username or not password:
            messagebox.showerror("Error", "Username and password are required.")
            return
            
        if len(password) < 6:
            messagebox.showerror("Error", "Password must be at least 6 characters.")
            return
            
        success = self.db.register_user(username, password)
        if success:
            messagebox.showinfo("Success", "Registration successful! You can now login.")
            self.password_entry.delete(0, tk.END)  # Clear password field
        else:
            messagebox.showerror("Error", "Username already exists.")

class TodoApp(tk.Frame):
    def __init__(self, parent, db, user_id, username, logout_callback):
        super().__init__(parent, bg="#f7f9f9")
        self.db = db
        self.user_id = user_id
        self.username = username
        self.logout_callback = logout_callback
        self.selected_todo_id = None
        self.current_date = None
        self.last_search_keyword = None  # Initialize search keyword tracking
        self.configure(padx=20, pady=20)
        
        # Center the frame within the parent
        parent.grid_rowconfigure(0, weight=1)
        parent.grid_columnconfigure(0, weight=1)
        self.grid(row=0, column=0, sticky="nsew")
        
        # Configure grid for centering content
        self.grid_rowconfigure(0, weight=1)
        self.grid_rowconfigure(2, weight=1)
        self.grid_columnconfigure(0, weight=1)
        self.grid_columnconfigure(2, weight=1)
        
        self.create_widgets()
        self.update_stats()  # Initialize stats
        
    def create_widgets(self):
        # Main content frame (centered) with background color
        main_content = tk.Frame(self, bg="#f7f9f9")
        main_content.grid(row=1, column=1)
        
        # Header with welcome message, stats, and logout button
        header_frame = tk.Frame(main_content, bg="#f7f9f9")
        header_frame.pack(fill="x", pady=(0, 15))
        
        welcome_label = tk.Label(header_frame, text=f"Welcome, {self.username}!", font=("Arial", 12, "bold"), bg="#f7f9f9")
        welcome_label.pack(side="left")

        # Add flags for tracking view state
        self.in_priority_view = False
        self.in_search_mode = False
        self.last_search_keyword = None
        
        # New: Add stats display
        self.stats_frame = tk.Frame(header_frame, bg="#f7f9f9")
        self.stats_frame.pack(side="left", padx=20)
        
        self.completed_label = tk.Label(self.stats_frame, text="Done: 0", font=("Arial", 10), bg="#f7f9f9", fg="#4CAF50")
        self.completed_label.pack(side="left", padx=5)
        
        self.pending_label = tk.Label(self.stats_frame, text="Pending: 0", font=("Arial", 10), bg="#f7f9f9", fg="#2196F3")
        self.pending_label.pack(side="left", padx=5)
        
        self.overdue_label = tk.Label(self.stats_frame, text="Overdue: 0", font=("Arial", 10), bg="#f7f9f9", fg="#f44336")
        self.overdue_label.pack(side="left", padx=5)
        
        logout_btn = tk.Button(header_frame, text="Logout", command=self.logout, bg="#f44336", fg="white")
        logout_btn.pack(side="right")
        
        # Content area (calendar + todo list)
        content_area = tk.Frame(main_content, bg="#f7f9f9")
        content_area.pack(fill="both", expand=True)
        
        # Left side with color #3498db - Calendar and Todo Form
        left_frame = tk.Frame(content_area, padx=10, bg="#3498db")
        left_frame.pack(side="left", fill="both", expand=True)
        
        # Calendar
        calendar_frame = tk.Frame(left_frame, bg="#3498db")
        calendar_frame.pack(fill="x")
        
        tk.Label(calendar_frame, text="Select Date:", font=("Arial", 10, "bold"), bg="#3498db", fg="white").pack(anchor="w", pady=(0, 5))
        self.calendar = cal.Calendar(calendar_frame, selectmode='day', 
                              date_pattern='yyyy-mm-dd',
                              background="#f7f9f9",
                              foreground="#333333",
                              selectbackground="#4CAF50")
        self.calendar.pack(fill="both", expand=True, pady=(0, 10))
        
        # Bind calendar selection event
        self.calendar.bind("<<CalendarSelected>>", self.date_selected)
        
        # Add Todo Form
        form_frame = tk.LabelFrame(left_frame, text="Add/Edit Todo", padx=10, pady=10, bg="#3498db", fg="white")
        form_frame.pack(fill="both", expand=True, pady=10)
        
        # Form fields
        form_content = tk.Frame(form_frame, bg="#3498db")
        form_content.pack(fill="both", expand=True)
        
        # Center the form contents
        form_content.grid_columnconfigure(0, weight=1)
        form_content.grid_columnconfigure(1, weight=1)
        
        # In the form_content part, add priority selection
        tk.Label(form_content, text="Title:", bg="#3498db", fg="white").grid(row=0, column=0, sticky="e", pady=5)
        self.title_entry = tk.Entry(form_content, width=30)
        self.title_entry.grid(row=0, column=1, padx=5, pady=5, sticky="w")
        
        tk.Label(form_content, text="Description:", bg="#3498db", fg="white").grid(row=1, column=0, sticky="ne", pady=5)
        self.description_text = tk.Text(form_content, width=30, height=5)
        self.description_text.grid(row=1, column=1, padx=5, pady=5)
        
        # Due time field
        tk.Label(form_content, text="Due Time (HH:MM):", bg="#3498db", fg="white").grid(row=2, column=0, sticky="e", pady=5)
        self.due_time_entry = tk.Entry(form_content, width=10)
        self.due_time_entry.grid(row=2, column=1, padx=5, pady=5, sticky="w")
        
        # New: Add priority selection
        tk.Label(form_content, text="Priority:", bg="#3498db", fg="white").grid(row=3, column=0, sticky="e", pady=5)
        self.priority_var = tk.StringVar(value="medium")
        self.priority_dropdown = ttk.Combobox(form_content, textvariable=self.priority_var, 
                                        values=["high", "medium", "low"], 
                                        state="readonly", width=10)
        self.priority_dropdown.grid(row=3, column=1, padx=5, pady=5, sticky="w")
        self.priority_dropdown.current(1) 
        
        # Center the buttons
        button_frame = tk.Frame(form_content, bg="#3498db")
        button_frame.grid(row=4, column=0, columnspan=2, pady=10)
        
        self.save_btn = tk.Button(button_frame, text="Add Todo", command=self.save_todo, 
                         bg="#4CAF50", fg="white", cursor="hand2")
        self.save_btn.pack(side="left", padx=5)
        
        self.clear_btn = tk.Button(button_frame, text="Clear Form", command=self.clear_form, bg="#ff9800", fg="white")
        self.clear_btn.pack(side="left", padx=5)
        
        # Right side with color #2c3e50 - Search and Todo List
        right_frame = tk.Frame(content_area, padx=10, bg="#2c3e50")
        right_frame.pack(side="right", fill="both", expand=True)

        show_all_btn = tk.Button(header_frame, text="Show All by Priority", 
                        command=self.show_all_by_priority, bg="#9b59b6", fg="white")
        show_all_btn.pack(side="right", padx=5)
        
        # Search box
        search_frame = tk.Frame(right_frame, bg="#2c3e50")
        search_frame.pack(fill="x", pady=(10, 5))
        
        # Center the search components
        search_frame.grid_columnconfigure(0, weight=1)
        search_frame.grid_columnconfigure(4, weight=1)
        
        tk.Label(search_frame, text="Search:", bg="#2c3e50", fg="white").grid(row=0, column=1, sticky="e", padx=(0, 5))
        self.search_entry = tk.Entry(search_frame, width=25)
        self.search_entry.grid(row=0, column=2, padx=5)
        
        button_container = tk.Frame(search_frame, bg="#2c3e50")
        button_container.grid(row=0, column=3, sticky="w")
        
        search_btn = tk.Button(button_container, text="Search", command=self.search_todos, bg="#2196F3", fg="white")
        search_btn.pack(side="left", padx=2)
        
        reset_btn = tk.Button(button_container, text="Reset", command=self.reset_search, bg="#607D8B", fg="white")
        reset_btn.pack(side="left", padx=2)
        
        # Todo list with scroll
        list_frame = tk.LabelFrame(right_frame, text="Your Todos", bg="#2c3e50", fg="white")
        list_frame.pack(fill="both", expand=True, pady=5)
        
        # Create treeview for todos
        style = ttk.Style()
        style.configure("Treeview", background="#f7f9f9", fieldbackground="#f7f9f9", rowheight=25)
        style.configure("Treeview.Heading", background="#e1e8ed", font=('Arial', 9, 'bold'))
        
        # Create treeview with date column and status
        self.tree = ttk.Treeview(list_frame, columns=("ID", "Date", "Title", "Description", "Status", "Due", "Priority"), show="headings", height=15)
        
        self.tree.heading("ID", text="ID")
        self.tree.heading("Date", text="Date")
        self.tree.heading("Title", text="Title")
        self.tree.heading("Description", text="Description")
        self.tree.heading("Status", text="Status")
        self.tree.heading("Due", text="Due Time")
        self.tree.heading("Priority", text="Priority")
        
        self.tree.column("ID", width=30, anchor="center")
        self.tree.column("Date", width=90, anchor="center")
        self.tree.column("Title", width=120)
        self.tree.column("Description", width=150)
        self.tree.column("Status", width=70, anchor="center")
        self.tree.column("Due", width=70, anchor="center")
        self.tree.column("Priority", width=70, anchor="center")
        
        # Configure tree tag colors - add priority colors
        self.tree.tag_configure('completed', background='#e8f5e9')
        self.tree.tag_configure('pending', background='white')
        self.tree.tag_configure('overdue', background='#ffebee')
        self.tree.tag_configure('high', foreground='#e74c3c')
        self.tree.tag_configure('medium', foreground='#f39c12')
        self.tree.tag_configure('low', foreground='#2ecc71')
        
        # Configure scrollbars for treeview
        v_scrollbar = ttk.Scrollbar(list_frame, orient="vertical", command=self.tree.yview)
        h_scrollbar = ttk.Scrollbar(list_frame, orient="horizontal", command=self.tree.xview)
        self.tree.configure(yscrollcommand=v_scrollbar.set, xscrollcommand=h_scrollbar.set)
        
        # Place the treeview and scrollbars
        self.tree.grid(row=0, column=0, sticky="nsew")
        v_scrollbar.grid(row=0, column=1, sticky="ns")
        h_scrollbar.grid(row=1, column=0, sticky="ew")
        
        # Configure grid weights for proper resizing
        list_frame.grid_rowconfigure(0, weight=1)
        list_frame.grid_columnconfigure(0, weight=1)
        
        # Add tooltip for treeview items to show full description
        self.tooltip = ToolTip(self.tree)
        self.tree.bind("<Motion>", self.show_tooltip)
        
        # Bind selection event
        self.tree.bind("<<TreeviewSelect>>", self.item_selected)
        
        # Action buttons - centered
        action_frame = tk.Frame(right_frame, bg="#2c3e50")
        action_frame.pack(fill="x", pady=5)
        
        # Center the buttons
        action_frame.grid_columnconfigure(0, weight=1)
        action_frame.grid_columnconfigure(3, weight=1)
        
        button_container = tk.Frame(action_frame, bg="#2c3e50")
        button_container.grid(row=0, column=1, columnspan=2)
        
        # New: Add "Mark as Done" button
        self.mark_done_btn = tk.Button(button_container, text="Mark as Done", command=self.mark_as_done, 
                                    bg="#4CAF50", fg="white")
        self.mark_done_btn.pack(side="left", padx=5)
        
        # New: Add "Mark as Pending" button
        self.mark_pending_btn = tk.Button(button_container, text="Mark as Pending", command=self.mark_as_pending, 
                                       bg="#FF9800", fg="white")
        self.mark_pending_btn.pack(side="left", padx=5)
        
        edit_btn = tk.Button(button_container, text="Edit Selected", command=self.edit_selected, bg="#2196F3", fg="white")
        edit_btn.pack(side="left", padx=5)
        
        delete_btn = tk.Button(button_container, text="Delete Selected", command=self.delete_selected, bg="#f44336", fg="white")
        delete_btn.pack(side="left", padx=5)
        
        # Initialize with today's todos
        today = datetime.date.today().strftime("%Y-%m-%d")
        self.calendar.selection_set(today)
        self.current_date = today
        self.load_todos_for_date(today)
    
    def update_stats(self):
        """Update the statistics display"""
        stats = self.db.get_todo_stats(self.user_id)
        self.completed_label.config(text=f"Done: {stats['completed']}")
        self.pending_label.config(text=f"Pending: {stats['pending']}")
        self.overdue_label.config(text=f"Overdue: {stats['overdue']}")
    
    def show_tooltip(self, event):
        """Display a tooltip with full description when hovering over an item"""
        item = self.tree.identify_row(event.y)
        if item:
            values = self.tree.item(item, "values")
            if values and len(values) > 3:  # If we have values and there's a description
                description = values[3]
                if description:
                    self.tooltip.show_tip(description)
                    return
        self.tooltip.hide_tip()

        
    def date_selected(self, event=None):
        selected_date = self.calendar.get_date()
        self.current_date = selected_date
        self.load_todos_for_date(selected_date)
        
    def load_todos_for_date(self, date):
        # Clear existing items
        for item in self.tree.get_children():
            self.tree.delete(item)
            
        # Load todos for the selected date
        todos = self.db.get_todos_by_date(self.user_id, date)
        
        # Current date and time for checking overdue
        now = datetime.datetime.now()
        current_date = now.strftime("%Y-%m-%d")
        current_time = now.strftime("%H:%M")
        
        for todo in todos:
            todo_id, todo_date, title, description, status, due_time, priority = todo
            
            # Determine if task is overdue
            tag = status
            if status == 'pending' and (todo_date < current_date or 
                                    (todo_date == current_date and due_time and due_time < current_time)):
                tag = 'overdue'
                
            item_id = self.tree.insert("", "end", 
                                values=(todo_id, todo_date, title, description, status, due_time or "", priority), 
                                tags=(tag, priority))
            
        # Update statistics
        self.update_stats()

    def show_all_by_priority(self):
        """Display all pending todos sorted by priority"""
        # Clear existing items
        for item in self.tree.get_children():
            self.tree.delete(item)
            
        # Set flag to indicate we're in priority view mode
        self.in_priority_view = True
        self.last_search_keyword = None  # Clear any search keyword
            
        # Load all todos sorted by priority
        todos = self.db.get_todos_by_priority(self.user_id)
        
        if not todos:
            messagebox.showinfo("Information", "No pending todos found")
            self.load_todos_for_date(self.current_date)
            self.in_priority_view = False  # Reset the flag
            return
        
        # Current date and time for checking overdue
        now = datetime.datetime.now()
        current_date = now.strftime("%Y-%m-%d")
        current_time = now.strftime("%H:%M")
        
        for todo in todos:
            todo_id, todo_date, title, description, status, due_time, priority = todo
            
            # Determine if task is overdue
            tag = status
            if status == 'pending' and (todo_date < current_date or 
                                    (todo_date == current_date and due_time and due_time < current_time)):
                tag = 'overdue'
                
            self.tree.insert("", "end", 
                        values=(todo_id, todo_date, title, description, status, due_time or "", priority), 
                        tags=(tag, priority))

    def clear_form(self):
        self.title_entry.delete(0, tk.END)
        self.description_text.delete(1.0, tk.END)
        self.due_time_entry.delete(0, tk.END)
        self.priority_var.set("medium")  # Reset priority to default
        self.selected_todo_id = None
        self.save_btn.config(text="Add Todo")
        
        # Deselect any selected item in the tree
        for selected_item in self.tree.selection():
            self.tree.selection_remove(selected_item)

    def _refresh_current_view(self):
        """Helper method to refresh the current view after adding/editing/deleting todos"""
        # After adding or updating a todo, we should always return to the selected date view
        # Reset view mode flags
        self.in_priority_view = False
        self.in_search_mode = False
        
        # Load todos for the current date
        self.load_todos_for_date(self.current_date)
        
    def save_todo(self):
        print("Save button clicked")  # Debug line
        title = self.title_entry.get().strip()
        description = self.description_text.get(1.0, tk.END).strip()
        due_time = self.due_time_entry.get().strip()
        priority = self.priority_var.get()
        
        print(f"Title: {title}, Priority: {priority}")  # Debug line
        
        # Validate due time format if provided
        if due_time and not self.validate_time_format(due_time):
            messagebox.showerror("Error", "Due time must be in HH:MM format")
            return
        
        if not title:
            messagebox.showerror("Error", "Title is required")
            return
        
        # Get selected date
        selected_date = self.calendar.get_date()
        current_date = datetime.date.today().strftime("%Y-%m-%d")
        
        # Check if trying to add a todo in the past
        if self.save_btn.cget("text") == "Add Todo" and selected_date < current_date:
            messagebox.showerror("Error", "Cannot add todos for past dates")
            return
        
        # Check if trying to add a todo for today but with past time
        if self.save_btn.cget("text") == "Add Todo" and selected_date == current_date and due_time:
            current_time = datetime.datetime.now().strftime("%H:%M")
            if due_time < current_time:
                messagebox.showerror("Error", "Cannot add todos with past time")
                return
                
        # Check if we're in edit mode or add mode
        if self.save_btn.cget("text") == "Update Todo":  # Update existing todo
            if self.selected_todo_id and self.db.update_todo(self.selected_todo_id, title, description, 
                            due_time if due_time else None, priority):
                messagebox.showinfo("Success", "Todo updated successfully")
                self.clear_form()
                # Reload the current view
                self._refresh_current_view()
            else:
                messagebox.showerror("Error", "Failed to update todo")
        else:  # Add new todo
            date = self.calendar.get_date()
            todo_id = self.db.add_todo(self.user_id, date, title, description, 
                                due_time if due_time else None, priority)
            if todo_id:
                messagebox.showinfo("Success", "Todo added successfully")
                self.clear_form()
                # Reload the current view
                self._refresh_current_view()
            else:
                messagebox.showerror("Error", "Failed to add todo")

    
    def validate_time_format(self, time_str):
        """Check if time string is in HH:MM format"""
        try:
            datetime.datetime.strptime(time_str, "%H:%M")
            return True
        except ValueError:
            return False
    
    def item_selected(self, event):
        selected_items = self.tree.selection()
        if selected_items:  # If something is selected
            item = selected_items[0]
            values = self.tree.item(item, "values")
            if values:
                # Only store the ID, don't fill the form automatically
                self.selected_todo_id = values[0]
        else:
            # Clear selected_todo_id if nothing is selected
            self.selected_todo_id = None
    
    def edit_selected(self):
        if not self.selected_todo_id:
            messagebox.showinfo("Info", "Please select a todo first")
            return
            
        selected_items = self.tree.selection()
        if selected_items:  # If something is selected
            item = selected_items[0]
            values = self.tree.item(item, "values")
            
            # Populate form for editing
            self.title_entry.delete(0, tk.END)
            self.title_entry.insert(0, values[2])  # Title
            
            self.description_text.delete(1.0, tk.END)
            self.description_text.insert(tk.END, values[3])  # Description
            
            # Set due time if it exists
            self.due_time_entry.delete(0, tk.END)
            if values[5] and values[5] != "None":  # Due time
                self.due_time_entry.insert(0, values[5])
                
            # Set priority
            if len(values) > 6 and values[6]:  # Priority
                self.priority_var.set(values[6])
            
            # Change button text to indicate update mode
            self.save_btn.config(text="Update Todo")
    

    # New: Mark selected todo as done
    def mark_as_done(self):
        if not self.selected_todo_id:
            messagebox.showinfo("Info", "Please select a todo first")
            return
            
        if self.db.mark_todo_as_done(self.selected_todo_id):
            messagebox.showinfo("Success", "Todo marked as completed")
            self._refresh_current_view()
            self.update_stats()
        else:
            messagebox.showerror("Error", "Failed to update todo status")
    
    # New: Mark selected todo as pending
    def mark_as_pending(self):
        if not self.selected_todo_id:
            messagebox.showinfo("Info", "Please select a todo first")
            return
            
        if self.db.mark_todo_as_pending(self.selected_todo_id):
            messagebox.showinfo("Success", "Todo marked as pending")
            self._refresh_current_view()
            self.update_stats()
        else:
            messagebox.showerror("Error", "Failed to update todo status")
    
    def delete_selected(self):
        if not self.selected_todo_id:
            messagebox.showinfo("Info", "Please select a todo first")
            return
            
        confirm = messagebox.askyesno("Confirm", "Are you sure you want to delete this todo?")
        if confirm:
            if self.db.delete_todo(self.selected_todo_id):
                messagebox.showinfo("Success", "Todo deleted successfully")
                self.selected_todo_id = None
                
                # Refresh the current view
                self._refresh_current_view()
                self.update_stats()
            else:
                messagebox.showerror("Error", "Failed to delete todo")
    
    def search_todos(self):
        keyword = self.search_entry.get().strip()
        if not keyword:
            messagebox.showinfo("Info", "Please enter a search keyword")
            return
            
        # Store the search keyword for possible reuse after deletion
        self.last_search_keyword = keyword
            
        # Clear existing items
        for item in self.tree.get_children():
            self.tree.delete(item)
            
        # Search todos
        todos = self.db.search_todos(self.user_id, keyword)
        if not todos:
            messagebox.showinfo("Search Results", "No todos found matching your search")
            return
            
        # Current date and time for checking overdue
        now = datetime.datetime.now()
        current_date = now.strftime("%Y-%m-%d")
        current_time = now.strftime("%H:%M")
        
        # Display results
        for todo in todos:
            todo_id, date, title, description, status, due_time, priority = todo
            
            # Determine if task is overdue
            tag = status
            if status == 'pending' and (date < current_date or 
                                    (date == current_date and due_time and due_time < current_time)):
                tag = 'overdue'
                
            self.tree.insert("", "end", 
                        values=(todo_id, date, title, description, status, due_time or "", priority), 
                        tags=(tag, priority))
    
    def reset_search(self):
        self.search_entry.delete(0, tk.END)
        self.last_search_keyword = None
        self.in_search_mode = False
        self.load_todos_for_date(self.current_date)
    
    def logout(self):
        confirm = messagebox.askyesno("Confirm", "Are you sure you want to logout?")
        if confirm:
            self.logout_callback()

class ToolTip:
    """Create a tooltip for a given widget"""
    def __init__(self, widget):
        self.widget = widget
        self.tip_window = None
        
    def show_tip(self, text):
        """Display text in a tooltip window"""
        if self.tip_window or not text:
            return
            
        # Get cursor position for tooltip placement
        x = self.widget.winfo_pointerx() + 15
        y = self.widget.winfo_pointery() + 10
        
        # Creates a toplevel window
        self.tip_window = tk.Toplevel(self.widget)
        self.tip_window.wm_overrideredirect(True)
        self.tip_window.wm_geometry(f"+{x}+{y}")
        
        label = tk.Label(self.tip_window, text=text, background="#ffffe0", 
                         relief="solid", borderwidth=1, wraplength=350, justify="left",
                         padx=5, pady=5)
        label.pack()
        
    def hide_tip(self):
        """Hide the tooltip"""
        if self.tip_window:
            self.tip_window.destroy()
            self.tip_window = None

class Application(tk.Tk):
    def __init__(self):
        super().__init__()
        
        self.title("Todo App")
        
        # Set minimum size
        self.minsize(1200, 600)
        
        # Start with a somewhat larger window
        self.geometry("1200x700")
        self.resizable(True, True)
        self.configure(bg="#f7f9f9")
        
        # Create database connection
        self.db = Database()
        
        # Center the window on the screen
        self.center_window()
        
        # Start with login frame
        self.show_login()
    
    def center_window(self):
        """Center the window on the screen"""
        # Get screen dimensions
        screen_width = self.winfo_screenwidth()
        screen_height = self.winfo_screenheight()
        
        # Calculate position
        x = (screen_width - 600) // 2
        y = (screen_height - 500) // 2
        
        # Set window position
        self.geometry(f"600x500+{x}+{y}")
        
    def show_login(self):
        # Clear current frame if any
        for widget in self.winfo_children():
            widget.destroy()
        
        # Create and show login frame
        login_frame = LoginFrame(self, self.db, self.show_main_app)
        
    def show_main_app(self, user_id, username):
        # Clear current frame
        for widget in self.winfo_children():
            widget.destroy()
        
        # Create and show main app
        todo_app = TodoApp(self, self.db, user_id, username, self.show_login)
        
    def on_closing(self):
        # Close database connection and exit
        if hasattr(self, 'db'):
            self.db.close()
        self.destroy()

if __name__ == "__main__":
    # Check if tkcalendar is installed, if not show installation instructions
    try:
        import tkcalendar
    except ImportError:
        print("This application requires the tkcalendar package.")
        print("Please install it using: pip install tkcalendar")
        input("Press Enter to exit...")
        exit()
        
    app = Application()
    app.protocol("WM_DELETE_WINDOW", app.on_closing)
    app.mainloop()