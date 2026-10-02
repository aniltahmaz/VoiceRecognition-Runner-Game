import queue
import sys
import json
import time
import array
from collections import deque

import sounddevice as sd
import vosk

from pythonosc.udp_client import SimpleUDPClient


# ============================================================
# SETTINGS
# ============================================================

MODEL_PATH = "model"

SAMPLE_RATE = 16000

# 320 samples at 16 kHz = 20 ms
BLOCK_SIZE = 320
# None = default Windows microphone
MIC_DEVICE = None


# ============================================================
# OSC / UNREAL
# ============================================================

OSC_IP = "127.0.0.1"
OSC_PORT = 8000
OSC_ADDRESS = "/voice/command"


# ============================================================
# COMMANDS
# ============================================================
#
# Must match the "withoutSpecialChar" column of DT_Words (Unreal Data
# Table) exactly. No special characters here; the accented display form
# is looked up on the Unreal side from DT_Words (ResolveDisplayWord).
# Python only recognizes this ASCII word and sends it as-is.

VOCABULARY = [
    "dzban",
    "dobry",
    "boczek",
    "morda",
    "moge",
    "jajko",
    "papierosy",
    "jak",
    "bigos",
    "czyli",
    "bober",
    "piwo",
    "dusza",
    "robak",
    "polska",
    "beka",
]


# ============================================================
# VOICE DETECTION
# ============================================================

# Voice must go ABOVE this to START a command.
VOICE_START_THRESHOLD = 800

# Voice must go BELOW this to count as silence.
#
# Lower than START threshold on purpose.
VOICE_END_THRESHOLD = 650


# After voice drops below END threshold,
# wait this long before forcing Vosk to finalize.
#
# Try:
# 0.15 = safer
# 0.10 = fast
# 0.07 = aggressive
SILENCE_TO_FINALIZE = 0.05

# Prevent tiny clicks/noises from instantly becoming attempts.
MIN_SPEECH_DURATION = 0.12


# Keep audio from slightly before VOICE START.
# Helps avoid chopping off first consonant.
PRE_ROLL_MS = 150


# If something goes wrong, abort attempt after this.
ATTEMPT_TIMEOUT = 2.0


# After an attempt, require silence before allowing
# another command.
REARM_SILENCE = 0.15


# ============================================================
# AUDIO QUEUE
# ============================================================

audio_queue = queue.SimpleQueue()


# ============================================================
# AUDIO CALLBACK
# ============================================================

def audio_callback(indata, frames, time_info, status):

    audio_queue.put(
        (
            time.perf_counter(),
            bytes(indata)
        )
    )


# ============================================================
# AUDIO PEAK
# ============================================================

def get_peak(data):

    samples = array.array("h")
    samples.frombytes(data)

    if not samples:
        return 0

    return max(abs(sample) for sample in samples)


# ============================================================
# CREATE VOSK RECOGNIZER
# ============================================================

def create_recognizer(model):

    grammar = json.dumps(
        VOCABULARY + ["[unk]"],
        ensure_ascii=False
    )

    recognizer = vosk.KaldiRecognizer(
        model,
        SAMPLE_RATE,
        grammar
    )

    recognizer.SetPartialWords(True)

    return recognizer


# ============================================================
# FIND COMMAND
# ============================================================

def find_command(text):

    words = text.lower().split()

    for word in words:

        if word in VOCABULARY:
            return word

    return None


# ============================================================
# SEND TO UNREAL
# ============================================================

def send_osc(
    osc,
    command,
    voice_start_time,
    recognition_source
):

    osc.send_message(
        OSC_ADDRESS,
        command
    )

    print(command)


# ============================================================
# MAIN
# ============================================================

def main():

    vosk.SetLogLevel(-1)


    # --------------------------------------------------------
    # Load model
    # --------------------------------------------------------

    model = vosk.Model(
        MODEL_PATH
    )


    # --------------------------------------------------------
    # OSC client
    # --------------------------------------------------------

    osc = SimpleUDPClient(
        OSC_IP,
        OSC_PORT
    )


    # --------------------------------------------------------
    # Pre-roll
    # --------------------------------------------------------

    block_duration = (
        BLOCK_SIZE / SAMPLE_RATE
    )

    block_duration_ms = (
        block_duration * 1000
    )


    pre_roll_blocks = max(
        1,
        round(
            PRE_ROLL_MS
            / block_duration_ms
        )
    )


    pre_roll = deque(
        maxlen=pre_roll_blocks
    )


    # --------------------------------------------------------
    # State
    # --------------------------------------------------------

    state = "ARMED"

    attempt_number = 0

    recognizer = None

    voice_start_time = None

    silence_start_time = None

    rearm_silence_start = None

    last_partial = ""


    # --------------------------------------------------------
    # Microphone
    # --------------------------------------------------------

    with sd.RawInputStream(

        device=MIC_DEVICE,

        samplerate=SAMPLE_RATE,

        blocksize=BLOCK_SIZE,

        latency="low",

        dtype="int16",

        channels=1,

        callback=audio_callback

    ) as stream:


        # ====================================================
        # LOOP
        # ====================================================

        while True:

            received_time, data = (
                audio_queue.get()
            )

            peak = get_peak(data)


            # =================================================
            # WAITING TO RE-ARM
            # =================================================

            if state == "WAIT_SILENCE":

                if peak < VOICE_END_THRESHOLD:

                    if rearm_silence_start is None:

                        rearm_silence_start = (
                            received_time
                        )


                    rearm_duration = (
                        received_time
                        - rearm_silence_start
                    )


                    if (
                        rearm_duration
                        >= REARM_SILENCE
                    ):

                        state = "ARMED"

                        rearm_silence_start = None

                        pre_roll.clear()


                else:

                    rearm_silence_start = None


                continue


            # =================================================
            # ARMED
            # =================================================

            if state == "ARMED":

                # Always retain latest audio for pre-roll.
                pre_roll.append(
                    (
                        received_time,
                        data
                    )
                )


                # No voice yet.
                if peak <= VOICE_START_THRESHOLD:

                    continue


                # =============================================
                # START ATTEMPT
                # =============================================

                attempt_number += 1

                state = "ACTIVE"

                voice_start_time = (
                    received_time
                )

                silence_start_time = None

                last_partial = ""


                recognizer = (
                    create_recognizer(model)
                )


                # ---------------------------------------------
                # Feed pre-roll including current block.
                # ---------------------------------------------

                for (
                    buffered_time,
                    buffered_data
                ) in pre_roll:

                    recognizer.AcceptWaveform(
                        buffered_data
                    )


                pre_roll.clear()


                # Current block was already in pre-roll,
                # so don't process it a second time.
                continue


            # =================================================
            # ACTIVE
            # =================================================

            if state == "ACTIVE":

                now = time.perf_counter()

                elapsed = (
                    now
                    - voice_start_time
                )


                # ---------------------------------------------
                # Feed current audio block to Vosk.
                # ---------------------------------------------

                auto_final = (
                    recognizer.AcceptWaveform(
                        data
                    )
                )


                # =============================================
                # PARTIAL RESULT
                # =============================================

                partial_json = json.loads(
                    recognizer.PartialResult()
                )


                partial = partial_json.get(
                    "partial",
                    ""
                ).strip().lower()


                if (
                    partial
                    and
                    partial != last_partial
                ):

                    last_partial = partial


                    command = (
                        find_command(partial)
                    )


                    # -----------------------------------------
                    # If Vosk gives us the command early,
                    # fire immediately.
                    # -----------------------------------------

                    if command is not None:

                        send_osc(
                            osc,
                            command,
                            voice_start_time,
                            "PARTIAL"
                        )


                        state = "WAIT_SILENCE"

                        recognizer = None

                        voice_start_time = None

                        silence_start_time = None

                        rearm_silence_start = None

                        last_partial = ""

                        continue


                # =============================================
                # MANUAL SILENCE DETECTION
                # =============================================

                elapsed = (
                    time.perf_counter()
                    - voice_start_time
                )


                # Don't attempt to finish immediately from
                # a tiny noise/click.
                if elapsed >= MIN_SPEECH_DURATION:

                    if peak < VOICE_END_THRESHOLD:

                        # First quiet block.
                        if silence_start_time is None:

                            silence_start_time = (
                                received_time
                            )


                        silence_duration = (
                            received_time
                            - silence_start_time
                        )


                        # =====================================
                        # WE DECIDE THE WORD IS FINISHED
                        # =====================================

                        if (
                            silence_duration
                            >= SILENCE_TO_FINALIZE
                        ):

                            final_json = json.loads(
                                recognizer.FinalResult()
                            )


                            final_text = final_json.get(
                                "text",
                                ""
                            ).strip().lower()


                            command = (
                                find_command(
                                    final_text
                                )
                            )


                            if command is not None:

                                send_osc(
                                    osc,
                                    command,
                                    voice_start_time,
                                    "FORCED FINAL"
                                )


                            # ---------------------------------
                            # Attempt finished.
                            # ---------------------------------

                            state = "WAIT_SILENCE"

                            recognizer = None

                            voice_start_time = None

                            silence_start_time = None

                            rearm_silence_start = None

                            last_partial = ""

                            continue


                    else:

                        # Voice became loud again, so the
                        # silence wasn't continuous.
                        silence_start_time = None


                # =============================================
                # VOSK AUTO-FINALIZED BEFORE US
                # =============================================

                if auto_final:

                    final_json = json.loads(
                        recognizer.Result()
                    )


                    final_text = final_json.get(
                        "text",
                        ""
                    ).strip().lower()


                    command = (
                        find_command(
                            final_text
                        )
                    )


                    if command:

                        send_osc(
                            osc,
                            command,
                            voice_start_time,
                            "VOSK AUTO FINAL"
                        )


                    state = "WAIT_SILENCE"

                    recognizer = None

                    voice_start_time = None

                    silence_start_time = None

                    rearm_silence_start = None

                    last_partial = ""

                    continue


                # =============================================
                # TIMEOUT
                # =============================================

                if elapsed >= ATTEMPT_TIMEOUT:

                    state = "WAIT_SILENCE"

                    recognizer = None

                    voice_start_time = None

                    silence_start_time = None

                    rearm_silence_start = None

                    last_partial = ""


# ============================================================
# START
# ============================================================

if __name__ == "__main__":

    try:

        main()


    except KeyboardInterrupt:

        pass


    except Exception as e:

        print(
            f"[ERROR] {e}",
            file=sys.stderr
        )
