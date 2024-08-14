from flask import Flask, render_template, request, jsonify
import calendar
from ortools.sat.python import cp_model

app = Flask(__name__)

class Employee:
    def __init__(self, name, weekday_shifts, weekend_shifts, unavailable_days, required_days):
        self.name = name
        self.weekday_shifts = weekday_shifts
        self.weekend_shifts = weekend_shifts
        self.unavailable_days = unavailable_days
        self.required_days = required_days

class SchedulingSystem:
    def __init__(self):
        self.year = 0
        self.month = 0
        self.first_day_of_week = 0
        self.num_days = 0
        self.holidays = []
        self.employees = []

    def initialize_month(self, year, month, holidays):
        self.year = year
        self.month = month
        self.first_day_of_week = calendar.weekday(year, month, 1)
        self.num_days = calendar.monthrange(year, month)[1]
        self.holidays = holidays

    def add_employee(self, name, weekday_shifts, weekend_shifts, unavailable_days, required_days):
        employee = Employee(name, weekday_shifts, weekend_shifts, unavailable_days, required_days)
        self.employees.append(employee)


    def remove_employee(self, name):
        self.employees = [e for e in self.employees if e.name != name]

    def create_schedule(self):
        model = cp_model.CpModel()
        shifts = {}

        for day in range(1, self.num_days + 1):
            for employee in self.employees:
                shifts[(day, employee.name)] = model.NewBoolVar(f'shift_{day}_{employee.name}')

        # 每天只需要有一名員工值班
        for day in range(1, self.num_days + 1):
            model.Add(sum(shifts[(day, employee.name)] for employee in self.employees) == 1)

        # 不可以連續兩天都是同一個人值班
        for day in range(1, self.num_days):
            for employee in self.employees:
                model.Add(shifts[(day, employee.name)] + shifts[(day + 1, employee.name)] <= 1)

        # 盡量不要間隔一天就又值班 (軟約束)
        for day in range(1, self.num_days - 2):
            for employee in self.employees:
                model.Add(shifts[(day, employee.name)] + shifts[(day + 2, employee.name)] <= 1)

        # 任意連續的7天內最多只能值3個班
        for day in range(1, self.num_days - 6):
            for employee in self.employees:
                model.Add(sum(shifts[(day + i, employee.name)] for i in range(7)) <= 3)

        # 員工不能值班的日期
        for employee in self.employees:
            for day in employee.unavailable_days:
                if 1 <= day <= self.num_days:  # 確保日期在有效範圍內
                    model.Add(shifts[(day, employee.name)] == 0)
        # 添加必須值班的約束
        for employee in self.employees:
            for day in employee.required_days:
                if 1 <= day <= self.num_days:
                    model.Add(shifts[(day, employee.name)] == 1)		

        # 平日班和假日班的數量限制
        for employee in self.employees:
            weekday_shifts = sum(shifts[(day, employee.name)] 
                                 for day in range(1, self.num_days + 1) 
                                 if (self.first_day_of_week + day - 1) % 7 < 5 and day not in self.holidays)
            weekend_shifts = sum(shifts[(day, employee.name)] 
                                 for day in range(1, self.num_days + 1) 
                                 if (self.first_day_of_week + day - 1) % 7 >= 5 or day in self.holidays)
            model.Add(weekday_shifts == employee.weekday_shifts)
            model.Add(weekend_shifts == employee.weekend_shifts)

        solver = cp_model.CpSolver()
        status = solver.Solve(model)

        if status == cp_model.OPTIMAL or status == cp_model.FEASIBLE:
            schedule = {}
            for day in range(1, self.num_days + 1):
                for employee in self.employees:
                    if solver.Value(shifts[(day, employee.name)]) == 1:
                        schedule[day] = employee.name
            return schedule, None
        else:
            return None, self.diagnose_scheduling_failure()
    def diagnose_scheduling_failure(self):
        total_weekday_shifts = sum(e.weekday_shifts for e in self.employees)
        total_weekend_shifts = sum(e.weekend_shifts for e in self.employees)
        required_weekday_shifts = len([d for d in range(1, self.num_days + 1) 
                                       if (self.first_day_of_week + d - 1) % 7 < 5 and d not in self.holidays])
        required_weekend_shifts = self.num_days - required_weekday_shifts

        if total_weekday_shifts != required_weekday_shifts:
            return f"Mismatch in weekday shifts. Required: {required_weekday_shifts}, Available: {total_weekday_shifts}"
        if total_weekend_shifts != required_weekend_shifts:
            return f"Mismatch in weekend shifts. Required: {required_weekend_shifts}, Available: {total_weekend_shifts}"
        
        # Check for potential conflicts with unavailable days
        for employee in self.employees:
            if len(employee.unavailable_days) > self.num_days - (employee.weekday_shifts + employee.weekend_shifts):
                return f"Employee {employee.name} has too many unavailable days"

        return "Unable to create a schedule. Please check the constraints and try again."

scheduling_system = SchedulingSystem()

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/initialize', methods=['POST'])
def initialize():
    data = request.json
    scheduling_system.initialize_month(data['year'], data['month'], data['holidays'])
    calendar_data = calendar.monthcalendar(data['year'], data['month'])
    return jsonify(success=True, calendar=calendar_data, holidays=scheduling_system.holidays)

@app.route('/add_employee', methods=['POST'])
def add_employee():
    data = request.json
    scheduling_system.add_employee(
        data['name'], 
        data['weekday_shifts'], 
        data['weekend_shifts'], 
        data['unavailable_days'],
        data['required_days']
    )
    return jsonify(success=True, employees=get_employees_data())

@app.route('/remove_employee', methods=['POST'])
def remove_employee():
    data = request.json
    scheduling_system.remove_employee(data['name'])
    return jsonify(success=True, employees=get_employees_data())

@app.route('/create_schedule', methods=['POST'])
def create_schedule():
    schedule, error = scheduling_system.create_schedule()
    if schedule:
        return jsonify(success=True, schedule=schedule, year=scheduling_system.year, month=scheduling_system.month)
    else:
        return jsonify(success=False, error=error), 400

def get_employees_data():
    return [{
        "name": e.name,
        "weekday_shifts": e.weekday_shifts,
        "weekend_shifts": e.weekend_shifts,
        "unavailable_days": e.unavailable_days,
        "required_days": e.required_days
    } for e in scheduling_system.employees]

if __name__ == '__main__':
    app.run(debug=True)