import streamlit as st
import os
from pymongo import MongoClient


st.set_page_config(page_title="TravenHealth", page_icon="🌊", layout="centered")

# 1. Establish Database Connection (Shares the exact same data cluster)
MONGO_URI = os.environ.get("MONGO_URI", "your_mongodb_uri")
DB_NAME = os.environ.get("MONGO_DB", "traven")

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

# Initialize Chat Interface
if "messages" not in st.session_state:
            st.session_state.messages = [{"role": "assistant", "content": "Hello! I am your Travenhealth assistant. Ask me anything about your current glucose metrics, diet adjustments, or metabolic insights!"}
    ]

# Display historical chat logs
for message in st.session_state.messages:
    with st.chat_message(message["role"]):
        st.markdown(message["content"])


# Process incoming input chat query from user
if prompt := st.chat_input("✨ Ask Traven a question..."):
    user_input = prompt.text
    st.session_state.messages.append({"role": "user", "content": user_input})
    with st.chat_message("user"):
        st.markdown(user_input)
        # Optional: Handle uploaded files if any...future feature
        #if prompt.files:
        #st.caption(f"📎 {len(prompt.files)} file(s) uploaded")


    with st.chat_message("assistant",avatar = "🌊"):
        # Setup for streaming
        streamer = TextIteratorStreamer(pipe.tokenizer, skip_prompt=True, skip_special_tokens=True)
        
        # Prepare arguments
        messages = st.session_state.messages # Use full history for context
        generation_kwargs = dict(
            text_inputs=messages, 
            streamer=streamer,
            max_new_tokens=512,
            do_sample=True,
            temperature=0.7,
            top_p=0.9
            )

        # Run generation in a background thread to prevent UI blocking
        thread = Thread(target=pipe, kwargs=generation_kwargs)
        thread.start()

        # Display the stream
        full_response = st.write_stream(streamer)

        st.session_state.messages.append({"role": "assistant", "content": full_response})

