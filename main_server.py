from flask import Flask, request, session, render_template, redirect, url_for, jsonify
import mysql.connector
import pymongo
import os
import jwt
import random
import string
from flask_bcrypt import Bcrypt
from flask_cors import CORS

from collections import defaultdict
from datetime import datetime,timedelta
from dateutil.relativedelta import relativedelta

app = Flask(__name__)
bcrypt = Bcrypt(app)
CORS(app)

#RETREIVE NECESSARY VALUES FROM ENVIRONMENTAL VARIABLES
app.secret_key = os.environ.get('APP_SECRET_KEY')
MONGO_DB_USERNAME = os.environ.get('MONGO_DB_USERNAME')
MONGO_DB_PW = os.environ.get('MONGO_PW')
MONGO_DB_DB = os.environ.get('MONGO_DB')
MONGO_DB_COL = os.environ.get('MONGO_COL')

db_config = {
    'host': os.environ.get('AWS_RDS_URI'),
    'user': os.environ.get('RDS_USERNAME'),
    'password': os.environ.get('RDS_PASSWORD'),
    'database': os.environ.get('RDS_DB_NAME'),
}

mess_db_config = {
    'host': os.environ.get('AWS_RDS_URI'),
    'user': os.environ.get('RDS_USERNAME'),
    'password': os.environ.get('RDS_PASSWORD'),
    'database': os.environ.get('RDS_DB_MESS_NAME'),
}

COOKIE_NAME = os.environ.get('COOKIE_NAME')

uri = f"mongodb+srv://{MONGO_DB_USERNAME}:{MONGO_DB_PW}@cluster0.wvhyisx.mongodb.net/?retryWrites=true&w=majority"
client = pymongo.MongoClient(uri)
db = client[MONGO_DB_DB]
col = db[MONGO_DB_COL]

#FUNCTIONS TO ENCODE AND DECODE THE USER ID BEFROE AND AFTER IT IS SENT OT THE FRONT-END
def encode(user_id):    
    payload = {'user_id': user_id}
    return jwt.encode(payload, app.secret_key ,algorithm='HS256')

def decode(payload):
    decoded_payload = jwt.decode(payload, app.secret_key , algorithms=['HS256'])    
    return decoded_payload['user_id']

###DEFINE INITIAL TEMPLATE ROUTES
@app.route('/')
def home():
    return redirect("https://landing.expense-tracker-demo.site/")

@app.route("/favicon.ico")
def favicon():
    return url_for('static', filename='data:,')

###USER LOGIN FUNCTIONALITY
@app.route('/user_login', methods=['POST','GET'])
def user_login():
        #Recieves the username and password from user
        username = request.json.get('username')
        password = request.json.get('password')
        #Connects to SQL database for user information and retreives the password
        conn = mysql.connector.connect(**db_config)
        cursor = conn.cursor()
        cursor.execute(f"SELECT pass FROM user_info WHERE userID = '{username}' LIMIT 1")
        pw = cursor.fetchone()
        if(not pw):
            return jsonify({'message': 'Invalid username or password'}), 200    
        conn.close

        #If the given credentials are correct, user is redirected to their dashoard
        if bcrypt.check_password_hash(pw[0], password):
            cursor.execute(f"SELECT id FROM user_info WHERE userID = '{username}' LIMIT 1")
            master_user_id = cursor.fetchone()
            master_user_id = master_user_id[0]
            encoded_id = encode(master_user_id)
            return jsonify({'message': 'Login successful','encoded_id':encoded_id}), 200
        #If the credentials are incorrect the page refrehes with an error message
        else:
            return jsonify({'message': 'Invalid username or password'}), 200


@app.route('/signup', methods=['GET','POST'])
def signup():
    return render_template('signup.html')

###Primary Sign-Up option is the traditional username-password method
@app.route('/signup_user', methods=['POST'])
def signup_user():
    
        #Request the user input from the input fields  
        username = request.json.get('username')
        password = request.json.get('password')

        #Connects to the database to check if a username already exists
        conn = mysql.connector.connect(**db_config)
        cursor = conn.cursor()
        cursor.execute(f"SELECT COUNT(id) FROM user_info where userID = '{username}'")
        taken = cursor.fetchone()
        
        #If the username already exists the user is prompted to choose a different one
        if taken[0] > 0:
            return jsonify({'message' : 'exists'})
                     
        #Password encrpytion
        password = bcrypt.generate_password_hash(password).decode('utf-8')
        query = f"INSERT INTO user_info VALUES (DEFAULT, '{username}', '{password}');"
        #If all requirements are met then an entry is creaated in the SQL databse with the user's credentials
        cursor.execute(query)
        conn.commit()

        cursor.execute(f"SELECT id FROM user_info WHERE userID = '{username}'")
        nosqlID = cursor.fetchone()
        nosqlID = nosqlID[0]
        col.insert_one({"_id": nosqlID,"income_types":[],"expense_types":[],"budget":{}})
        
        #User is redirected to the login page to sign in
        return jsonify({'message' : 'success'})

####DASHBOARD
#########################################################################
@app.route('/dashboard', methods = ['GET'])
def dashboard():    
    return render_template('dashboard.html')

#Retreives income and expense data from the SQL database and returns them to the front-end
@app.route('/get_income_v_expense', methods = ['POST'])
def get_income_v_expense():
    #gets and decodes the encoded user id from the front end
    encoded_id = request.json.get('encoded_id')
    master_user_id = decode(encoded_id)
    income = []
    expenses = []

    #Using decoded user id, retrevie the income data from the SQL database
    query = f"SELECT SUM(amount) AS total_income, DATE_FORMAT(STR_TO_DATE(day_month_year, '%Y-%m-%d'), '%Y-%m') AS month FROM user_income WHERE user_id = {master_user_id} GROUP BY month ORDER BY month desc LIMIT 12;"
    conn = mysql.connector.connect(**db_config)
    cursor = conn.cursor()
    cursor.execute(query)
    data = cursor.fetchall()    
    for row in data:
        income.append(dict(zip([column[0] for column in cursor.description], row)))

    #Using decoded user id, retrevie the expenses data from the SQL database
    query = f"SELECT SUM(amount) AS total_expenses, DATE_FORMAT(STR_TO_DATE(day_month_year, '%Y-%m-%d'), '%Y-%m') AS month FROM user_expenses WHERE user_id = {master_user_id} GROUP BY month ORDER BY month desc LIMIT 12;"
    conn = mysql.connector.connect(**db_config)
    cursor = conn.cursor()
    cursor.execute(query)
    data = cursor.fetchall()    
    for row in data:
        expenses.append(dict(zip([column[0] for column in cursor.description], row)))        
    conn.close
    
    #if there is either no income or expenses data the front-end recieves no data
    if len(income) == 0 and len(expenses) == 0:
        response = {'status' : 'no_data'}
        return jsonify(response)

    combined_dict = defaultdict(lambda: {'expenses': 0, 'income': 0})
    current_date = datetime.now()

    # Create a set to store the last 12 months
    last_12_months = set()

    # Loop through the last 12 months and add them to the set
    for i in range(12):
        last_month = current_date - relativedelta(months=i)
        last_12_months.add(last_month.strftime('%Y-%m'))

    for date in last_12_months:
        for item in expenses:
            if item['month'] == date:
                combined_dict[date]['expenses'] = item['total_expenses']
                break
        for item in income:
            if item['month'] == date:
                combined_dict[date]['income'] = item['total_income']
                break
    
    for date in last_12_months:
        if combined_dict[date]['expenses'] == 0 and combined_dict[date]['income'] == 0:
            combined_dict[date] = {'expenses': 0, 'income': 0}
    
    income_expense = {"income_expense":combined_dict}

    return jsonify(income_expense)

#Retreives a breakdown of each income type and returns it to the front-end
@app.route('/get_income_breakdown', methods = ['POST'])
def get_income_breakdown():
    encoded_id = request.json.get('encoded_id')
    master_user_id = decode(encoded_id)
    incomes = []

    one_year_ago = datetime.now() - timedelta(days=365)
    one_year_ago = datetime(one_year_ago.year, one_year_ago.month + 1, 1)
    one_year_ago = one_year_ago.strftime('%Y-%m-%d')

    query = f"SELECT DATE_FORMAT(STR_TO_DATE(day_month_year, '%Y-%m-%d'), '%Y-%m') AS month, income_type, SUM(amount) AS income_type_sum FROM user_income WHERE user_id = {master_user_id} AND day_month_year > {one_year_ago} GROUP BY month, income_type ORDER BY month, income_type;"
    conn = mysql.connector.connect(**db_config)
    cursor = conn.cursor()
    cursor.execute(query)
    data = cursor.fetchall()    
    for row in data:
        incomes.append(dict(zip([column[0] for column in cursor.description], row)))        
    conn.close
    
    if len(incomes) == 0:
        response = {'status' : 'no_data'}
        return jsonify(response)


    #Get all possible income sub-categories  
    incomeTypes = col.find_one({"_id": master_user_id})
    income_cats = incomeTypes['income_types']

    # Create a defaultdict to store combined expenses
    combined_incomes = defaultdict(lambda: defaultdict(int))

    # Combine expenses
    for income in incomes:
        date = income["month"]
        subcategory = income["income_type"]
        amount = income["income_type_sum"]
        combined_incomes[date][subcategory] += amount

    # Create entries for the last 12 months
    end_date = datetime.now().replace(day=1)
    start_date = end_date - relativedelta(months=11)

    current_date = start_date
    while current_date <= end_date:
        current_date_str = current_date.strftime("%Y-%m")
        if current_date_str not in combined_incomes:
            combined_incomes[current_date_str] = defaultdict(int)
        current_date += relativedelta(months=1)

    # Convert defaultdict to regular dictionary
    combined_incomes = dict(combined_incomes)

    # Fill in missing subcategories with 0
    for date in combined_incomes:
        subcategories = combined_incomes[date].keys()
        all_subcategories = set(income_cats)  # Add all possible subcategories
        missing_subcategories = all_subcategories - set(subcategories)
        for subcategory in missing_subcategories:
            combined_incomes[date][subcategory] = 0

    # Sort the combined expenses by date
    sorted_combined_incomes = dict(sorted(combined_incomes.items()))

    return jsonify({"sorted_combined_incomes":sorted_combined_incomes})

@app.route('/get_expense_breakdown', methods = ['POST'])
def get_expense_breakdown():
    encoded_id = request.json.get('encoded_id')
    master_user_id = decode(encoded_id)
    expenses = []

    one_year_ago = datetime.now() - timedelta(days=365)
    one_year_ago = datetime(one_year_ago.year, one_year_ago.month + 1, 1)
    one_year_ago = one_year_ago.strftime('%Y-%m-%d')

    query = f"SELECT DATE_FORMAT(STR_TO_DATE(day_month_year, '%Y-%m-%d'), '%Y-%m') AS month, expense_type, SUM(amount) AS expense_type_sum FROM user_expenses WHERE user_id = {master_user_id} AND day_month_year > {one_year_ago} GROUP BY month, expense_type ORDER BY month, expense_type;"
    conn = mysql.connector.connect(**db_config)
    cursor = conn.cursor()
    cursor.execute(query)
    data = cursor.fetchall()    
    for row in data:
        expenses.append(dict(zip([column[0] for column in cursor.description], row)))
    conn.close

    if len(expenses) == 0:
        response = {'status' : 'no_data'}
        return jsonify(response)
    
    #Get all possible income sub-categories 
         
    incomeTypes = col.find_one({"_id": master_user_id})
    expense_cats = incomeTypes['expense_types']

    # Create a defaultdict to store combined expenses
    combined_expenses = defaultdict(lambda: defaultdict(int))

    # Combine expenses
    for expense in expenses:
        date = expense["month"]
        subcategory = expense["expense_type"]
        amount = expense["expense_type_sum"]
        combined_expenses[date][subcategory] += amount

    # Create entries for the last 12 months
    end_date = datetime.now().replace(day=1)
    start_date = end_date - relativedelta(months=11)

    current_date = start_date
    while current_date <= end_date:
        current_date_str = current_date.strftime("%Y-%m")
        if current_date_str not in combined_expenses:
            combined_expenses[current_date_str] = defaultdict(int)
        current_date += relativedelta(months=1)

    # Convert defaultdict to regular dictionary
    combined_expenses = dict(combined_expenses)

    # Fill in missing subcategories with 0
    for date in combined_expenses:
        subcategories = combined_expenses[date].keys()
        all_subcategories = set(expense_cats)  # Add all possible subcategories
        missing_subcategories = all_subcategories - set(subcategories)
        for subcategory in missing_subcategories:
            combined_expenses[date][subcategory] = 0

    # Sort the combined expenses by date
    sorted_combined_expenses = dict(sorted(combined_expenses.items()))
    
    ###
    return jsonify({"sorted_combined_expenses":sorted_combined_expenses})


@app.route('/get_budget_recent_expenses', methods = ['POST'])
def get_budget_recent_expenses():
    encoded_id = request.json.get('encoded_id')
    master_user_id = decode(encoded_id)
    monthly_expenses = []

    budget_targets = col.find_one({"_id": master_user_id})
    budget_targets = budget_targets['budget']

    query = f"SELECT expense_type, SUM(amount) AS total_amount FROM user_expenses WHERE user_id = {master_user_id} AND YEAR(day_month_year) = YEAR(CURDATE()) AND MONTH(day_month_year) = MONTH(CURDATE()) GROUP BY expense_type;"
    conn = mysql.connector.connect(**db_config)
    cursor = conn.cursor()
    cursor.execute(query)
    data = cursor.fetchall() 
    for row in data:
        monthly_expenses.append(dict(zip([column[0] for column in cursor.description], row)))
    conn.close

    if len(budget_targets) == 0 or len(monthly_expenses) == 0:
        response = {'status' : 'no_data'}
        return jsonify(response)
    return jsonify({'budget' : budget_targets, 'monthly_expenses' : monthly_expenses})


####INCOME
#########################################################################
### REDIRECT USER TO INCOME HUB 
@app.route('/income', methods = ['GET'])
def income():
    return render_template('add_income.html')

### ADDS USER INCOME TO SQL DATABASE USING INFORMATION PORVIDED BY JAVASCRIPT REQUEST
@app.route('/add_income', methods=['POST','GET'])
def add_income():
    #PARSE DATA FROM JAVASCRIPT REQUEST
    incomeType = request.json.get('incomeType')
    amount = request.json.get('amount')
    date = request.json.get('date')
    encoded_id = request.json.get('encoded_id')
    user = decode(encoded_id)

    #DATA INSERTION INTO SQL DATABSE
    conn = mysql.connector.connect(**db_config)
    cursor = conn.cursor()
    cursor.execute(f"INSERT INTO user_income VALUES (DEFAULT, '{user}', '{date}','{incomeType}','{amount}');")
    conn.commit()
    conn.close
    return jsonify({'message' : 'success'})

###FUNCTIONALITY TO GET THE VAROIUS INCOME TYPES THAT A USER HAS STORED IN 
# THEIR NOSQL DOCUMENT AND RETURNS THE RESULTS TO THE JAVASCRIPT FONT-END
@app.route('/get_income_types', methods = ['POST'])
def get_income_types():
    encoded_id = request.json.get('encoded_id')
    master_user_id = decode(encoded_id)
    incomeTypes = col.find_one({"_id": master_user_id})
    incomeTypes = incomeTypes['income_types']
    return jsonify({'types':incomeTypes})

###FUNCTIONALITY TO ADD A NEW INCOMETYPE TO THE USER'S NOSQL DOCUMENT
@app.route('/add_income_type', methods = ['POST'])
def add_income_type():
    newIncomeType = request.json.get('newIncomeType')
    encoded_id = request.json.get('encoded_id')
    master_user_id = decode(encoded_id)

    #Gets all the INCOME TYPES in the current user's NoSQL document
    incomeTypes = col.find_one({"_id": master_user_id})
    incomeTypes = incomeTypes['income_types'] 

    #If the income type trying to be added already exists, return an "exists" message to the JavaScript front-end
    if(newIncomeType in incomeTypes):
        return jsonify({'message' : 'exists'})

    #If the income type doesn't exist in the document, it is pushed onto user's NoSQL document
    col.update_one({"_id" : master_user_id}, { "$push" : {"income_types" : newIncomeType}})
    return jsonify({'message' : 'success'})

### FUNCTIONALITY TO REMOVE AN INCOME TYPE FROM THE USER'S NOSQL DOCUMENT
@app.route('/remove_income_type', methods=['POST'])
def remove_income_type():
    # Get the income type to be removed from the JavaScript request
    incomeTypeTBR = request.json.get('incomeTypeTBR')
    encoded_id = request.json.get('encoded_id')
    master_user_id = decode(encoded_id)

    # Removes the selected income type from the user's NoSQL document
    col.update_one({"_id" : master_user_id}, { "$pull" : {"income_types" : incomeTypeTBR}})

    # Resturns a "success" response message to the JavaScript front-end
    return jsonify({'status': 'success'})

### FUNCTIONALITY TO GET THE RECENT INCOME ENTRIES THE USER HAS ADDED TO THE SQL DATABSE
@app.route('/get_recent_income', methods = ['POST'])
def get_recent_income():
    encoded_id = request.json.get('encoded_id')
    master_user_id = decode(encoded_id)
    recent_income_entries = []

    # Queries the database to fetch all income entries for the current user
    query = f"SELECT income_id, user_id, income_type, amount, day_month_year FROM user_income WHERE user_id = {master_user_id} ORDER BY day_month_year DESC;"
    conn = mysql.connector.connect(**db_config)
    cursor = conn.cursor()
    cursor.execute(query)
    data = cursor.fetchall()
    
    for row in data:
        formatted_date = row[4].strftime('%m-%d-%Y')
        formatted_entry = {
            'income_id': row[0],
            'user_id': row[1],
            'income_type': row[2],
            'amount': row[3],
            'date': formatted_date
        }
        recent_income_entries.append(formatted_entry)
    conn.close
    # Returns the results of the query to the Javascript front-end
    return jsonify({'entries' : recent_income_entries})

###FUNCTIONALITY TO REMOVE A SPECIFIC ENTRY FROM THE SQL DATABSE OF INCOME ENTRIES
@app.route('/delete_income_entry',methods = ['POST'])
def delete_income_entry():
    # Retreives the unique id of the income entry that is to be deleted
    incomeEntryTBR = request.json.get('incomeEntryTBR')
    encoded_id = request.json.get('encoded_id')
    master_user_id = decode(encoded_id)
    conn = mysql.connector.connect(**db_config)
    cursor = conn.cursor()
    # Crestes and commits a quesry to delete the entry from the database
    cursor.execute(f"DELETE FROM user_income WHERE income_id = {incomeEntryTBR} AND user_id = {master_user_id};")
    conn.commit()
    conn.close

    # Return "succes message to the Javascript front-end"
    return jsonify({'status': 'success'})


##EXPENSES
#################################################################

### REDIRECT USER TO EXPENSES HUB
@app.route('/expenses', methods = ['GET'])
def expenses():
    return render_template('add_expense.html')

### FUNCTIONALITY TO ADD A NEW EXPENSE TO THE SQL DATABASE
@app.route('/add_expense', methods = ['POST'])
def add_expense():
    # Parse data from Javascript request
    expenseType = request.json.get('expenseType')
    amount = request.json.get('amount')
    date = request.json.get('date')
    encoded_id = request.json.get('encoded_id')
    user = decode(encoded_id)

    # Create and execute a query that will insert the data into the SQL databse
    conn = mysql.connector.connect(**db_config)
    cursor = conn.cursor()
    cursor.execute(f"INSERT INTO user_expenses VALUES (DEFAULT, '{user}', '{date}','{expenseType}','{amount}');")
    conn.commit()
    conn.close
    return jsonify({'message' : 'success'})

###FUNCTIONALITY TO GET ALL THE USER'S EXPENSE TYPES FOR THIER NOSQL DOCUMENT
@app.route('/get_expense_types', methods = ['POST'])
def get_expense_types():
    encoded_id = request.json.get('encoded_id')
    master_user_id = decode(encoded_id)
    expenseTypes = col.find_one({"_id": master_user_id})
    expenseTypes = expenseTypes['expense_types']
    return jsonify({'types':expenseTypes})

### FUNCTINALITY TO ADD AN EXPENSE TYPE THE USER'S NOSQL DOCUMENT
@app.route('/add_expense_type', methods = ['POST'])
def add_expense_type():
    newExpenseType = request.json.get('newExpenseType')
    encoded_id = request.json.get('encoded_id')
    master_user_id = decode(encoded_id)

    #Gets all expense types in the current user's NoSQL document
    expenseTypes = col.find_one({"_id": master_user_id})
    expenseTypes = expenseTypes['expense_types'] 

    #If expense type exists, return "exists" message to JavaScript front-end
    if(newExpenseType in expenseTypes):
        return jsonify({'message' : 'exists'})

    #If the expense types doesn't exist in the document, it is pushed onto the user's NoSQL document
    col.update_one({"_id" : master_user_id}, { "$push" : {"expense_types" : newExpenseType}})
    return jsonify({'message' : 'success'})

### FUNCTIONALITY TO REMOVE AN EXPENSE TYPE FROM THE USER'S NOSQL DOCUMENT
@app.route('/remove_expense_type', methods=['POST'])
def remove_expense_type():
    # Get the expense type to be removed from the JavaScript request    
    expenseTypeTBR = request.json.get('expenseTypeTBR')
    encoded_id = request.json.get('encoded_id')

    master_user_id = decode(encoded_id)

    # Remove the selected expense type from the user's NOSQL document
    col.update_one({"_id" : master_user_id}, { "$pull" : {"expense_types" : expenseTypeTBR}})

    # Return a "success" response to the JavaScript front-end
    return jsonify({'status': 'success'})

### FUNCTIONALITY TO GET ALL THE EXPENSE ENTRIES THE USER INPUTTED INTO THE SQL DATABASAE
@app.route('/get_recent_expenses', methods = ['POST'])
def get_recent_expenses():
    # Gets user's id from session
    encoded_id = request.json.get('encoded_id')
    master_user_id = decode(encoded_id)
    recent_expense_entries = []

    # Creates and executes query to return all expense entries inputted by the user
    query = f"SELECT expense_id, user_id, expense_type, amount, day_month_year FROM user_expenses WHERE user_id = {master_user_id} ORDER BY day_month_year DESC;"
    conn = mysql.connector.connect(**db_config)
    cursor = conn.cursor()
    cursor.execute(query)
    data = cursor.fetchall()
    
    for row in data:
        formatted_date = row[4].strftime('%m-%d-%Y')
        formatted_entry = {
            'expense_id': row[0],
            'user_id': row[1],
            'expense_type': row[2],
            'amount': row[3],
            'date': formatted_date
        }
        recent_expense_entries.append(formatted_entry)    
    conn.close
    
    # Returns te expense entries to the JavaScript from-end
    return jsonify({'entries' : recent_expense_entries})

### FUNCTIONALITY TO DELETE A SPECIFIC EXPENSE ENTRY FROM THE SQL DATASE
@app.route('/delete_expense_entry',methods = ['POST'])
def delete_expense_entry():
    expenseEntryTBR = request.json.get('expenseEntryTBR')
    encoded_id = request.json.get('encoded_id')
    master_user_id = decode(encoded_id)
    conn = mysql.connector.connect(**db_config)
    cursor = conn.cursor()

    # Creates and executes a query to delete the expense entry selected by the user
    cursor.execute(f"DELETE FROM user_expenses WHERE expense_id = {expenseEntryTBR} AND user_id = {master_user_id};")
    conn.commit()
    conn.close

    # Return "success" message to front-end
    return jsonify({'status': 'success'})

##BUDGET
#################################################################
### REDIRECT USER TO EXPENSES HUB
@app.route('/budget', methods = ['GET'])
def budget():
    return render_template('budget.html')

@app.route('/get_budget_targets', methods = ['POST'])
def get_budget_targets():
    encoded_id = request.json.get('encoded_id')
    master_user_id = decode(encoded_id)
    budget_targets = col.find_one({"_id": master_user_id})
    budget_targets = budget_targets['budget']
    return jsonify({'types':budget_targets})

@app.route('/save_budget', methods = ['POST'])
def save_budget():    
    expenseType = request.json.get('expenseType')
    newBudgetAmount = request.json.get('newBudgetAmount')
    encoded_id = request.json.get('encoded_id')
    master_user_id = decode(encoded_id)
    newBudgetAmount = int(newBudgetAmount)   
    nested = "budget."+expenseType

    result = col.update_one({'_id': master_user_id},{'$set': {nested: newBudgetAmount}}, upsert=True)

    if result.upserted_id:
        return jsonify({'status':'success'})
    else:
        return jsonify({'status':'fail'})

####LOGOUT FUNCTOINALITY
@app.route('/logout', methods=['POST'])
def logout():
    #Remove the current user's unique identifyer from the session object
    session.pop("user",None)

    #Redirects user back to the home landing page after logging out
    return jsonify({'status':'loggedOUT'})

@app.route('/gen_password', methods=['POST','GET'])
def gen_password():
    length = request.json.get('length')
    length = int(length)
    inc_sym = request.json.get('includeSymbolsValue')
    inc_num = request.json.get('includeNumbersValue')
    inc_upp = request.json.get('includeUppercaseValue')

    pw = ""
    n = 0

    while(n <= length):
        rand_num = random.randint(0, 3)

        if(rand_num == 0):
            random_letter = random.choice(string.ascii_letters)
            pw += random_letter.lower()
            n = n+1

        elif(inc_upp and rand_num == 1):
            random_letter = random.choice(string.ascii_letters)
            pw += random_letter.upper()
            n = n+1

        elif(inc_num and rand_num == 2):
            random_number = random.randint(0, 9)
            pw += str(random_number)
            n = n+1

        elif(inc_sym and rand_num == 3):
            symbols = ['!', '@', '#', '$', '%', '^', '&', '*']
            random_symbol = random.choice(symbols)
            pw += random_symbol
            n = n+1
        
    return jsonify({'password': pw}), 200

@app.route('/save_massage', methods=['POST','GET'])
def save_message():
    name = request.json.get('name')
    email = request.json.get('email')
    mess = request.json.get('mess')

    conn = mysql.connector.connect(**mess_db_config)
    cursor = conn.cursor()
    # Crestes and commits a quesry to delete the entry from the database
    query = f"INSERT INTO messages VALUES (DEFAULT, '{name}', '{email}', '{mess}');"
    cursor.execute(query)
    conn.commit()
    conn.close
        
    return jsonify({'message': 'success'}), 200

if __name__ == '__main__':
    app.run(debug=True)