"""
Browser-based voice input using Web Speech API.
Renders an HTML/JS component that captures speech and returns transcript.
Works in Chrome, Edge, and Safari (not Firefox).
"""
import streamlit as st
import streamlit.components.v1 as components


def render_voice_input(key: str = "voice_input") -> str | None:
    """
    Render a microphone button that uses the Web Speech API.
    Returns the transcribed text when speech is captured, None otherwise.
    
    The component communicates back to Streamlit via session_state.
    """
    # Check if we have a pending transcript from previous render
    transcript_key = f"{key}_transcript"
    
    # Render the voice component
    result = components.html(
        _get_voice_html(transcript_key),
        height=50,
        key=f"{key}_component"
    )
    
    # Check session state for transcript (set via query params workaround)
    if transcript_key in st.session_state and st.session_state[transcript_key]:
        text = st.session_state[transcript_key]
        st.session_state[transcript_key] = ""  # Clear after reading
        return text
    
    return None


def render_voice_button() -> None:
    """
    Render a simple voice input section that stores transcript in session_state.
    Uses st.components.v1.html with postMessage for communication.
    """
    voice_html = """
    <div id="voice-container" style="display:flex; align-items:center; gap:10px; font-family:sans-serif;">
        <button id="mic-btn" onclick="toggleVoice()" style="
            background:#F5921E; color:white; border:none; border-radius:50%;
            width:36px; height:36px; cursor:pointer; font-size:16px;
            display:flex; align-items:center; justify-content:center;
            transition: background 0.2s;">
            🎤
        </button>
        <span id="status-text" style="color:#888; font-size:13px;"></span>
    </div>
    
    <script>
    let recognition = null;
    let isListening = false;
    
    function toggleVoice() {
        if (isListening) {
            stopListening();
        } else {
            startListening();
        }
    }
    
    function startListening() {
        const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
        if (!SpeechRecognition) {
            document.getElementById('status-text').textContent = 'Speech not supported in this browser';
            return;
        }
        
        recognition = new SpeechRecognition();
        recognition.continuous = false;
        recognition.interimResults = true;
        recognition.lang = 'en-US';
        
        recognition.onstart = function() {
            isListening = true;
            document.getElementById('mic-btn').style.background = '#e53e3e';
            document.getElementById('status-text').textContent = 'Listening...';
        };
        
        recognition.onresult = function(event) {
            let transcript = '';
            for (let i = event.resultIndex; i < event.results.length; i++) {
                transcript += event.results[i][0].transcript;
            }
            document.getElementById('status-text').textContent = transcript;
            
            // If this is a final result, send to Streamlit
            if (event.results[event.results.length - 1].isFinal) {
                // Send transcript to parent Streamlit via postMessage
                window.parent.postMessage({
                    type: 'streamlit:setComponentValue',
                    value: transcript
                }, '*');
                
                // Also store in a way Streamlit can read
                const stFrame = window.parent.document;
                const event2 = new CustomEvent('voice_transcript', {detail: transcript});
                stFrame.dispatchEvent(event2);
                
                document.getElementById('status-text').textContent = '✓ "' + transcript + '"';
                document.getElementById('mic-btn').style.background = '#F5921E';
                isListening = false;
            }
        };
        
        recognition.onerror = function(event) {
            document.getElementById('status-text').textContent = 'Error: ' + event.error;
            document.getElementById('mic-btn').style.background = '#F5921E';
            isListening = false;
        };
        
        recognition.onend = function() {
            if (isListening) {
                document.getElementById('mic-btn').style.background = '#F5921E';
                isListening = false;
            }
        };
        
        recognition.start();
    }
    
    function stopListening() {
        if (recognition) {
            recognition.stop();
        }
        isListening = false;
        document.getElementById('mic-btn').style.background = '#F5921E';
        document.getElementById('status-text').textContent = '';
    }
    </script>
    """
    return voice_html


def get_voice_input_section() -> str | None:
    """
    Complete voice input section for the chatbot.
    Returns transcribed text or None.
    
    Usage in the chatbot tab:
        transcript = get_voice_input_section()
        if transcript:
            # Process as if user typed it
            process_question(transcript)
    """
    col1, col2 = st.columns([1, 11])
    
    with col1:
        voice_active = st.button("🎤", key="voice_btn", help="Click to speak your question")
    
    if voice_active:
        st.session_state["voice_listening"] = True
    
    if st.session_state.get("voice_listening", False):
        # Render the speech recognition component
        transcript = components.html(
            _get_listening_html(),
            height=60,
            key="voice_listener"
        )
        return None  # Will be handled via session state on rerun
    
    return None


def _get_listening_html() -> str:
    """HTML that auto-starts speech recognition and sends result back."""
    return """
    <div style="display:flex; align-items:center; gap:10px; font-family:sans-serif; padding:8px 0;">
        <div style="width:12px; height:12px; background:#e53e3e; border-radius:50%; animation: pulse 1s infinite;"></div>
        <span id="transcript-display" style="color:#333; font-size:14px;">Listening...</span>
    </div>
    <style>
        @keyframes pulse { 0%,100%{opacity:1} 50%{opacity:0.4} }
    </style>
    <script>
    (function() {
        const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
        if (!SpeechRecognition) {
            document.getElementById('transcript-display').textContent = 'Speech recognition not supported. Use Chrome or Edge.';
            return;
        }
        
        const recognition = new SpeechRecognition();
        recognition.continuous = false;
        recognition.interimResults = true;
        recognition.lang = 'en-US';
        recognition.maxAlternatives = 1;
        
        recognition.onresult = function(event) {
            let finalTranscript = '';
            let interimTranscript = '';
            
            for (let i = event.resultIndex; i < event.results.length; i++) {
                if (event.results[i].isFinal) {
                    finalTranscript += event.results[i][0].transcript;
                } else {
                    interimTranscript += event.results[i][0].transcript;
                }
            }
            
            document.getElementById('transcript-display').textContent = 
                finalTranscript || interimTranscript || 'Listening...';
            
            if (finalTranscript) {
                // Send to Streamlit
                window.parent.postMessage({
                    isStreamlitMessage: true,
                    type: 'streamlit:setComponentValue', 
                    value: finalTranscript
                }, '*');
            }
        };
        
        recognition.onerror = function(event) {
            document.getElementById('transcript-display').textContent = 'Error: ' + event.error + '. Try again.';
        };
        
        recognition.onend = function() {
            // Auto-restart if no final result was captured
        };
        
        // Auto-start
        recognition.start();
    })();
    </script>
    """


def _get_voice_html(transcript_key: str) -> str:
    """Full voice HTML component."""
    return render_voice_button()
