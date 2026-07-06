from database import (
    create_database,
    import_students_from_excel,
    import_teachers_from_excel,
    populate_ce2_data,
    populate_ce1_data,
)

# Make sure all tables (including the routine table) exist
create_database()

# Import students and teachers from Excel sheets
import_students_from_excel('students.xlsx')
import_teachers_from_excel('teachers.xlsx')

# Seed CE-II/II subjects + weekly routine
populate_ce2_data()

# Seed CE-I/II MATH104 (Dr. Sushil Ghimire) — simplified, no section split
populate_ce1_data()
