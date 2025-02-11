import os
import pickle
import smtplib
import socket
import threading
from datetime import datetime
from threading import Lock
import cv2
import face_recognition as fr
import requests
from flask import Flask, render_template, Response, jsonify
from dotenv import load_dotenv
import time
# Load environment variables
load_dotenv()

# Configuration
path = "static/train_images"
my_email = os.getenv("EMAIL")
password = os.getenv("EMAIL_PASSWORD")
allowed_hours = os.getenv("ALLOWED_HOURS", "8,10,12").split(",")
REMOTE_SERVER = os.getenv("REMOTE_SERVER", "one.one.one.one")
images_to_read = os.listdir(path)
names = [name.split(".")[0] for name in images_to_read]
date = datetime.now().strftime("%d-%m-%Y")
file_path = f"Attendance_File/{date}.csv"
students = []
students_lock = Lock()
app = Flask(__name__)

# Ensure required directories exist
os.makedirs("Attendance_File", exist_ok=True)
os.makedirs("static/train_images", exist_ok=True)


# Load or encode face images
def encode_and_save_images(images_to_encode, filename):
    """Encode and save face images to a file."""
    print("Encoding Started")
    encoded_list = [fr.face_encodings(cv2.cvtColor(imgs, cv2.COLOR_BGR2RGB))[0] for imgs in images_to_encode]
    with open(filename, 'wb') as file:
        pickle.dump(encoded_list, file)
    print("Encoded images saved to", filename)


def load_encoded_images(filename):
    """Load encoded face images from a file."""
    try:
        with open(filename, 'rb') as file:
            encoded_list = pickle.load(file)
            return encoded_list
    except FileNotFoundError:
        return []


def get_status(c_hour, c_minute):
    """Determine attendance status based on time."""
    if c_hour in allowed_hours and 0 <= c_minute <= 15:
        return "Present"
    elif c_hour in allowed_hours and 16 <= c_minute <= 30:
        return "Late"
    else:
        return "Absent"


def is_connected(hostname):
    """Check internet connectivity."""
    try:
        host = socket.gethostbyname(hostname)
        s = socket.create_connection((host, 80), 5)
        s.close()
        return True
    except socket.gaierror:
        time.sleep(0.3)
    return False


def mark_attendance(name):
    """Mark attendance for a detected student."""
    now = datetime.now().strftime("%I:%M:%S")
    hour = str(datetime.now().hour)
    minute = datetime.now().minute
    status = get_status(hour, minute)

    if os.path.isfile(file_path):
        with open(file_path, "r+") as file:
            data = file.readlines()[1:]
            name_list = [line.split(",")[0] for line in data]
            if name not in name_list:
                file.writelines(f"\n{name},{now},{status}")
                number = get_phone_number(name)
                detected_names = [name, status, now, date]
                with students_lock:
                    students.append(detected_names)

                if "96" not in number:
                    threading.Thread(target=send_email, args=(number, status, now)).start()
                else:
                    threading.Thread(target=whatsapp_message, args=(number, status, now)).start()
    else:
        with open(file_path, "a") as file:
            file.write("Name,Time,status")
            file.writelines(f"\n{name},{now},{status}")
        detected_names = [name, status, now, date]
        with students_lock:
            students.append(detected_names)

        number = get_phone_number(name)
        if "96" not in number:
            threading.Thread(target=send_email, args=(number, status, now)).start()
        else:
            threading.Thread(target=whatsapp_message, args=(number, status, now)).start()


def whatsapp_message(number, status, now):
    """Send WhatsApp message using Green API."""
    message = (f'{{\n\t"chatId": "{int(number)}@c.us",\n\t"message": "*Smart Attendance*\\n\\n*Status:* {status}\\n'
               f'*Date:* {date}\\n*Time:* {now}"\n}}')

    idInstance = os.getenv("WHATSAPP_ID")
    apiTokenInstance = os.getenv("WHATSAPP_API_TOKEN")

    url_sending_msg = f"https://api.green-api.com/waInstance{idInstance}/sendMessage/{apiTokenInstance}"

    headers = {
        'Content-Type': 'application/json'
    }

    try:
        response = requests.post(url_sending_msg, headers=headers, data=message)
        if response.status_code == 200:
            print("WhatsApp Message Sent Successfully")
        else:
            print("Failed To Send Whatsapp Message")
    except Exception as e:
        print("No Internet Connection")
        print("Failed To Send Message")
        print(e)


def send_email(email, status, now):
    """Send email notification."""
    email_msg = f"Subject: Smart Attendance\n\nStatus: {status} \nDate: {date} \nTime:{now}"

    try:
        with smtplib.SMTP("smtp.gmail.com", 587) as connection:
            connection.starttls()
            connection.login(my_email, password)
            connection.sendmail(from_addr=my_email, to_addrs=email, msg=email_msg)
            print("Email Message Successfully Sent")
    except Exception as e:
        print("Failed To Send Email")
        print(e)


def get_phone_number(student_name):
    """Get phone number or email from Students_data.csv."""
    try:
        with open("Students_data.csv") as file:
            data = file.readlines()
            for row in data:
                name, number = row.split(",")
                if name == student_name:
                    return number.strip()
    except FileNotFoundError:
        print("Students_data.csv not found")
    return ""


def scan_images():
    """Load or encode face images."""
    try:
        with open("signed_students.csv", "r") as names_file:
            names_to_scan = names_file.readlines()
            names_to_check = [name.strip() for name in names_to_scan]

            set_s_img = set(names_to_check)
            set_img = set(names)

            different_names = list(set_s_img.symmetric_difference(set_img))
            if different_names:
                images = [cv2.imread(f"{path}/{imgs}") for imgs in images_to_read]
                encode_and_save_images(images, "encoded_images.pkl")

                with open("signed_students.csv", "w") as new_names_file:
                    for name in names:
                        new_names_file.writelines(f"{name}\n")
                return load_encoded_images("encoded_images.pkl")
            else:
                return load_encoded_images("encoded_images.pkl")
    except FileNotFoundError:
        print("signed_students.csv not found")
        return []


def wait_connection():
    """Wait for internet connection."""
    if not is_connected(REMOTE_SERVER):
        print("Please Connect to Internet")
        while not is_connected(REMOTE_SERVER):
            pass


known_faces = scan_images()
wait_connection()

start = True
cap = cv2.VideoCapture(0)


def generate_frames():
    """Generate video frames for Flask."""
    global start
    while start:
        success, img = cap.read()
        if not success:
            continue
        img_resized = cv2.resize(img, (0, 0), None, 0.25, 0.25)
        img_resized = cv2.cvtColor(img_resized, cv2.COLOR_BGR2RGB)
        faces_location = fr.face_locations(img_resized, model="hog")
        encode_faces = fr.face_encodings(img_resized, faces_location)
        for encodeFace, faceLocation in zip(encode_faces, faces_location):
            matches = fr.compare_faces(known_faces, encodeFace, tolerance=0.5)
            faces_distance = fr.face_distance(known_faces, encodeFace)
            matches_index = faces_distance.argmin()
            if matches[matches_index] and faces_distance.min() <= 0.5:
                detected_name = names[matches_index]
                y1, x2, y2, x1 = [coord * 4 for coord in faceLocation]
                cv2.rectangle(img, (x1, y1), (x2, y2), (0, 255, 0), 2)
                cv2.rectangle(img, (x1, y2 - 35), (x2, y2), (0, 255, 0), cv2.FILLED)
                cv2.putText(img, detected_name, (x1 + 6, y2 - 6), cv2.FONT_HERSHEY_COMPLEX, 1, (255, 255, 255), 2)
                threading.Thread(target=mark_attendance, args=(detected_name,)).start()
        ret, buffer = cv2.imencode('.jpg', img)
        if not ret:
            continue
        frame = buffer.tobytes()
        yield (b'--frame\r\n'
               b'Content-Type: image/jpeg\r\n\r\n' + frame + b'\r\n')


@app.route('/')
def index():
    """Render the main page."""
    return render_template('index.html', detected_name=students,
                           time=datetime.now().strftime("%I:%M:%S"), date=date)


@app.route('/get_attendance_data')
def get_attendance_data():
    """
    Return the latest attendance data in JSON format.
    """
    with students_lock:
        return jsonify(students)


@app.route('/video_feed')
def video_feed():
    """Stream video frames."""
    global start
    if not start:
        start = True
    return Response(generate_frames(), mimetype='multipart/x-mixed-replace; boundary=frame')


@app.route('/stop_recording', methods=['GET'])
def stop_recording():
    """Stop video recording."""
    global start
    start = False
    cap.release()
    cv2.destroyAllWindows()
    return 'Recording stopped'


if __name__ == '__main__':
    app.run(debug=False, port=5006)