import os
import csv
import shutil
import zipfile
import streamlit as st
from jinja2 import Template
import pandas as pd
from sqlalchemy import create_engine, Column, Integer, String, Text, DateTime
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
from datetime import datetime

# --- SQLite setup ---
Base = declarative_base()

class PromptTemplate(Base):
    __tablename__ = 'templates'
    id = Column(Integer, primary_key=True)
    name = Column(String, unique=True, nullable=False)
    content = Column(Text, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

engine = create_engine('sqlite:///templates.db')
Base.metadata.create_all(engine)
Session = sessionmaker(bind=engine)

# --- Paths ---
DATA_DIR = "data"
OUTPUT_DIR = "generated_prompts"
ZIP_PATH = "output.zip"
TEMPLATE_DIR = "templates"

os.makedirs(DATA_DIR, exist_ok=True)
os.makedirs(OUTPUT_DIR, exist_ok=True)

# --- Load templates from file every time ---
session = Session()
existing_names = {tpl.name for tpl in session.query(PromptTemplate.name).all()}
fallback_files = [f for f in os.listdir(TEMPLATE_DIR) if f.endswith(".txt")]
for file in fallback_files:
    name = file.replace(".txt", "")
    with open(os.path.join(TEMPLATE_DIR, file), 'r', encoding='utf-8') as f:
        content = f.read()
    if name in existing_names:
        existing_tpl = session.query(PromptTemplate).filter_by(name=name).first()
        existing_tpl.content = content  # Always update content
    else:
        tpl = PromptTemplate(name=name, content=content)
        session.add(tpl)
session.commit()

# --- Utils ---
def clean_row(row):
    return {k.strip().replace('\ufeff', ''): v.strip() if isinstance(v, str) else '' for k, v in row.items() if isinstance(k, str)}

def render_prompts(template_str, csv_path):
    with open(csv_path, 'r', encoding='utf-8-sig') as f:
        reader = csv.DictReader(f)
        prompts = []
        for idx, row in enumerate(reader, start=1):
            clean = clean_row(row)
            t = Template(template_str)
            result = t.render(**clean)
            filename = f"prompt_{idx}.txt"
            filepath = os.path.join(OUTPUT_DIR, filename)
            with open(filepath, 'w', encoding='utf-8') as out:
                out.write(result)
            prompts.append((filename, result))
        return prompts

def zip_output():
    with zipfile.ZipFile(ZIP_PATH, 'w') as zipf:
        for file in os.listdir(OUTPUT_DIR):
            file_path = os.path.join(OUTPUT_DIR, file)
            zipf.write(file_path, arcname=file)

# --- Streamlit GUI ---
st.set_page_config(layout="wide")
st.title("📦 Prompt Factory with SQLite CMS + Backup Files")

# --- CMS Sidebar ---
st.sidebar.header("🗂️ Prompt Template Manager")
mode = st.sidebar.radio("Mode", ["Load", "Create", "Edit", "Delete"])

if mode == "Create":
    new_name = st.sidebar.text_input("Template Name")
    new_content = st.sidebar.text_area("Template Content", height=300)
    if st.sidebar.button("Save Template") and new_name and new_content:
        if session.query(PromptTemplate).filter_by(name=new_name).first():
            st.sidebar.error("Template with this name already exists.")
        else:
            tpl = PromptTemplate(name=new_name, content=new_content)
            session.add(tpl)
            session.commit()
            st.sidebar.success("Template saved.")

elif mode == "Edit":
    all_templates = session.query(PromptTemplate).all()
    names = [tpl.name for tpl in all_templates]
    edit_choice = st.sidebar.selectbox("Select Template", names)
    selected_tpl = session.query(PromptTemplate).filter_by(name=edit_choice).first()
    edited_content = st.sidebar.text_area("Edit Content", selected_tpl.content, height=300)
    if st.sidebar.button("Update Template"):
        selected_tpl.content = edited_content
        session.commit()
        st.sidebar.success("Template updated.")

elif mode == "Delete":
    all_templates = session.query(PromptTemplate).all()
    names = [tpl.name for tpl in all_templates]
    delete_choice = st.sidebar.selectbox("Select Template to Delete", names)
    if st.sidebar.button("Delete Template"):
        to_delete = session.query(PromptTemplate).filter_by(name=delete_choice).first()
        if to_delete:
            session.delete(to_delete)
            session.commit()
            st.sidebar.success("Template deleted.")

# --- Main Template Selection ---
all_templates = session.query(PromptTemplate).all()
selected_name = st.selectbox("Select Template to Use", [tpl.name for tpl in all_templates])
selected_template = session.query(PromptTemplate).filter_by(name=selected_name).first()
csv_file = st.file_uploader("Upload a CSV File", type=["csv"])

if selected_template and csv_file:
    st.success("Ready to generate prompts")
    if st.button("🚀 Generate Prompts"):
        shutil.rmtree(OUTPUT_DIR)
        os.makedirs(OUTPUT_DIR, exist_ok=True)

        # Save uploaded CSV temporarily
        temp_csv_path = os.path.join(DATA_DIR, "uploaded.csv")
        with open(temp_csv_path, "wb") as f:
            f.write(csv_file.getbuffer())

        # Generate prompts and store in session
        st.session_state['results'] = render_prompts(selected_template.content, temp_csv_path)
        zip_output()

        st.success(f"{len(st.session_state['results'])} prompts generated ✅")
        st.download_button("📥 Download ZIP", data=open(ZIP_PATH, "rb"), file_name="prompts.zip")

if 'results' in st.session_state:
    with st.expander("🔍 Preview Prompts"):
        for i, (name, text) in enumerate(st.session_state['results'][:10]):
            st.text(f"📄 {name}")
            st.code(text, language='text')
