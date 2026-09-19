import streamlit as st
import os
from pymongo import MongoClient
from huggingface_hub import InferenceClient

st.set_page_config(page_title="TravenHealth", page_icon="🌊", layout="centered")

# 1. Establish Database Connection using Streamlit Secrets
MONGO_URI = st.secrets["mongo_uri"]
DB_NAME = st.secrets.get("mongo_db", "traven")

@st.cache_resource
def get_db_collection():
    client = MongoClient(MONGO_URI, tls=True, tlsAllowInvalidCertificates=True)
    return client[DB_NAME]["users"]

users_col = get_db_collection()


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


# 4. Initialize the Serverless Inference Client using Secrets
# Make sure your secrets.toml has: hf_token = "..."
@st.cache_resource
def get_hf_client():
    return InferenceClient(api_key=st.secrets["hf_token"])

hf_client = get_hf_client()


# ─────────────────────────────────────────────────────────────
# STREAMLIT UI DESIGN & INTERACTIVE HEALTH CHAT
# ─────────────────────────────────────────────────────────────
st.title("Traven AI 👋🏼")
st.subheader(f"Patient File Metrics: ID {user_whatsapp_id}")
st.markdown("---")

st.info("📊 *Glucose Sync Active:* Real-time data visualization layout module loading below...")

# Initialize Chat Interface with a System Prompt context hidden inside state
if "messages" not in st.session_state:
    st.session_state.messages = [
        {"role": "assistant", "content": "Hello! I am your Travenhealth assistant. Ask me anything about your current glucose metrics, diet adjustments, or metabolic insights!"}
    ]

# Display historical chat logs
for message in st.session_state.messages:
    with st.chat_message(message["role"]):
        st.markdown(message["content"])


# Process incoming input chat query from user
if prompt := st.chat_input("✨ Ask Traven a question..."):
    st.session_state.messages.append({"role": "user", "content": prompt})
    with st.chat_message("user"):
        st.markdown(prompt)

    with st.chat_message("assistant", avatar="🌊"):
        
        # Inject context instructions implicitly without cluttering user screen UI
        system_context = {
            "role": "system",
            "content": f"You are the senior metabolic health AI for Travenhealth. You are talking to patient {user_whatsapp_id}. Provide actionable guidance based on their metrics."
        }
        
        # Build payload history combining the hidden system guidelines + the active dialogue
        payload_messages = [system_context] + st.session_state.messages

        # Call the serverless cloud stream API natively
        stream = hf_client.chat.completions.create(
            model="Qwen/Qwen2.5-0.5B-Instruct",
            messages=payload_messages,
            max_tokens=512,
            temperature=0.7,
            stream=True,
        )
        
        # Clean helper generator wrapper to match Streamlit's write_stream canvas requirements
        def stream_response_handler():
            for chunk in stream:
                content_piece = chunk.choices[0].delta.content or ""
                yield content_piece

        # Render the text beautifully in real-time across the screen
        full_response = st.write_stream(stream_response_handler())

        st.session_state.messages.append({"role": "assistant", "content": full_response})
