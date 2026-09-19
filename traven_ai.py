import streamlit as st
import os
from pymongo import MongoClient
from google import genai

st.set_page_config(page_title="TravenHealth", page_icon="🌊", layout="centered")

# 1. Establish Database Connection (Shares the exact same data cluster)
MONGO_URI = os.environ.get("MONGO_URI", "your_mongodb_uri")
DB_NAME = os.environ.get("MONGO_DB", "traven")

@st.cache_resource
def get_db_collection():
    client = MongoClient(MONGO_URI, tls=True, tlsAllowInvalidCertificates=True)
    return client[DB_NAME]["users"]

users_col = get_db_collection()
ai_client = genai.Client()

# 2. Extract the WhatsApp ID directly out of the browser URL bar parameters
query_params = st.query_params
user_whatsapp_id = query_params.get("wa_id")

if not user_whatsapp_id:
    st.error("🔒 Unauthorized Session. Please access this portal securely via your official Travenhealth WhatsApp link.")
    st.stop()

# 3. Verify user connection profile status inside MongoDB
user_profile = users_col.find_one({"wa_id": user_whatsapp_id})

if not user_profile:
    st.warning("⚠️ Your account connection profile is incomplete. Please type 'Hi' on WhatsApp to finish onboarding.")
    st.stop()



@st.cache_resource
def load_pipeline():
    # Adding torch_dtype="auto" or "float16" speeds up GPU inference
    return pipeline("text-generation", model="Qwen/Qwen2.5-0.5B-Instruct", dtype=torch.float16)
pipe = load_pipeline()





# ─────────────────────────────────────────────────────────────
# STREAMLIT UI DESIGN & INTERACTIVE HEALTH CHAT
# ─────────────────────────────────────────────────────────────
st.title("Traven AI 👋🏼")
st.subheader(f"Patient File Metrics: ID {user_whatsapp_id}")
st.markdown("---")

# Visual placeholder where your upcoming sensor charts will go
st.info("📊 *Glucose Sync Active:* Real-time data visualization layout module loading below...")

# Core conversational chat interface state initializations
if "messages" not in st.session_state:
    st.session_state.messages = [
        {"role": "assistant", "content": "Hello! I am your Travenhealth assistant. Ask me anything about your current glucose metrics, diet adjustments, or metabolic insights!"}
    ]

# Display historical chat log history across screen refreshes
for msg in st.session_state.messages:
    with st.chat_message(msg["role"]):
        st.write(msg["content"])

# Process incoming input chat query strings from the patient
if user_prompt := st.chat_input("Ask Traven a question about your health data..."):
    # Append user prompt to dashboard canvas screen display
    st.session_state.messages.append({"role": "user", "content": user_prompt})
    with st.chat_message("user"):
        st.write(user_prompt)
        
    # Generate intelligent metabolic responses completely free of Meta transaction fees
    with st.chat_message("assistant"):
        with st.spinner("Analyzing metrics..."):
            
            # Context window reinforcement payload architecture
            context_prompt = (
                f"You are the senior metabolic health tracker AI for Travenhealth. "
                f"You are speaking with patient account {user_whatsapp_id}. Provide highly scientific, actionable, "
                f"yet easy-to-understand lifestyle guidance based on their metrics."
            )
            
            response = ai_client.models.generate_content(
                model='gemini-2.5-flash',
                contents=[context_prompt, user_prompt]
            )
            
            st.write(response.text)
            st.session_state.messages.append({"role": "assistant", "content": response.text})
