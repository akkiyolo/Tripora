/* ============================================================
   TRIPORA FRONTEND
============================================================ */


/* ============================================================
   STATE
============================================================ */

let currentThreadId =
    localStorage.getItem("travel_thread_id") || null;

let latestAnswerMarkdown = "";

let processingInterval = null;


/* ============================================================
   DOM
============================================================ */

const userInput = document.getElementById("userInput");
const sendBtn = document.getElementById("sendBtn");
const btnText = document.getElementById("btnText");
const btnLoader = document.getElementById("btnLoader");
const btnArrow = document.getElementById("btnArrow");

const resultSection =
    document.getElementById("resultSection");

const resultBox =
    document.getElementById("resultBox");

const threadInfo =
    document.getElementById("threadInfo");

const errorBox =
    document.getElementById("errorBox");

const processingCard =
    document.getElementById("processingCard");

const processingText =
    document.getElementById("processingText");

const charCount =
    document.getElementById("charCount");

const newTripBtn =
    document.getElementById("newTripBtn");


/* ============================================================
   QUICK PROMPTS
============================================================ */

function setPrompt(text) {

    userInput.value = text;

    updateCharacterCount();

    userInput.focus();

    userInput.setSelectionRange(
        userInput.value.length,
        userInput.value.length
    );
}


/* ============================================================
   CHARACTER COUNT
============================================================ */

function updateCharacterCount() {

    const length = userInput.value.length;

    charCount.textContent =
        `${length.toLocaleString()} / 2000`;

    if (length > 1800) {
        charCount.style.color = "#d86c3d";
    } else {
        charCount.style.color = "";
    }
}


/* ============================================================
   LOADING STATE
============================================================ */

function setLoading(isLoading) {

    sendBtn.disabled = isLoading;

    if (isLoading) {

        btnText.textContent = "Planning";

        btnLoader.classList.remove("hidden");

        btnArrow.classList.add("hidden");

        processingCard.classList.remove("hidden");

        startProcessingMessages();

    } else {

        btnText.textContent = "Build my trip";

        btnLoader.classList.add("hidden");

        btnArrow.classList.remove("hidden");

        processingCard.classList.add("hidden");

        stopProcessingMessages();
    }
}


/* ============================================================
   PROCESSING MESSAGES
============================================================ */

const processingMessages = [
    "Searching for the best options...",
    "Checking flights and destinations...",
    "Finding suitable stays...",
    "Putting your itinerary together...",
    "Balancing time, budget and experiences...",
    "Almost there..."
];

function startProcessingMessages() {

    let index = 0;

    processingText.textContent =
        processingMessages[index];

    processingInterval =
        setInterval(() => {

            index =
                (index + 1) %
                processingMessages.length;

            processingText.textContent =
                processingMessages[index];

        }, 2200);
}


function stopProcessingMessages() {

    if (processingInterval) {

        clearInterval(processingInterval);

        processingInterval = null;
    }
}


/* ============================================================
   ERROR HANDLING
============================================================ */

function showError(message) {

    errorBox.textContent = message;

    errorBox.classList.remove("hidden");

    errorBox.scrollIntoView({
        behavior: "smooth",
        block: "center"
    });
}


function hideError() {

    errorBox.classList.add("hidden");

    errorBox.textContent = "";
}


/* ============================================================
   SHOW RESULT
============================================================ */

function showResult(answer, threadId) {

    latestAnswerMarkdown = answer;

    if (
        typeof marked !== "undefined"
    ) {

        resultBox.innerHTML =
            marked.parse(answer);

    } else {

        resultBox.innerText = answer;
    }


    threadInfo.textContent =
        threadId || "Current session";


    resultSection.classList.remove("hidden");


    setTimeout(() => {

        resultSection.scrollIntoView({
            behavior: "smooth",
            block: "start"
        });

    }, 80);
}


/* ============================================================
   SEND MESSAGE
============================================================ */

async function sendMessage() {

    hideError();

    const message =
        userInput.value.trim();


    if (!message) {

        showError(
            "Tell us a little about your trip first."
        );

        userInput.focus();

        return;
    }


    if (message.length > 2000) {

        showError(
            "Your request is too long. Keep it under 2000 characters."
        );

        return;
    }


    setLoading(true);


    try {

        const response =
            await fetch(
                "/api/travel",
                {
                    method: "POST",

                    headers: {
                        "Content-Type":
                            "application/json"
                    },

                    body: JSON.stringify({
                        message: message,

                        thread_id:
                            currentThreadId
                    })
                }
            );


        let data;

        try {

            data =
                await response.json();

        } catch {

            throw new Error(
                "The server returned an invalid response."
            );
        }


        if (
            !response.ok ||
            !data.success
        ) {

            throw new Error(
                data.error ||
                "Something went wrong while planning your trip."
            );
        }


        currentThreadId =
            data.thread_id;


        if (currentThreadId) {

            localStorage.setItem(
                "travel_thread_id",
                currentThreadId
            );
        }


        showResult(
            data.answer,
            data.thread_id
        );


    } catch (error) {

        console.error(
            "Tripora request failed:",
            error
        );

        showError(
            error.message ||
            "Unable to connect to Tripora."
        );

    } finally {

        setLoading(false);
    }
}


/* ============================================================
   COPY RESULT
============================================================ */

async function copyResult() {

    const text =
        resultBox.innerText.trim();


    if (!text) {

        showError(
            "There is no travel plan to copy yet."
        );

        return;
    }


    const copyButton =
        document.querySelector(
            ".secondary-btn"
        );


    try {

        await navigator.clipboard.writeText(text);


        const original =
            copyButton.innerHTML;


        copyButton.innerHTML =
            "<span>Copied</span>";


        setTimeout(() => {

            copyButton.innerHTML =
                original;

        }, 1500);


    } catch (error) {

        showError(
            "Could not copy the travel plan."
        );
    }
}


/* ============================================================
   DOWNLOAD PDF
============================================================ */

function downloadPDF() {

    const pdfContent =
        document.getElementById("pdfContent");


    if (
        !latestAnswerMarkdown ||
        !pdfContent
    ) {

        showError(
            "There is no travel plan available to download."
        );

        return;
    }


    if (
        typeof html2pdf === "undefined"
    ) {

        showError(
            "PDF library could not be loaded. Check your internet connection."
        );

        return;
    }


    const downloadButton =
        document.querySelector(
            ".primary-small-btn"
        );


    const originalHTML =
        downloadButton.innerHTML;


    downloadButton.innerHTML =
        "<span>Preparing...</span>";


    downloadButton.disabled = true;


    const options = {

        margin: [
            0.45,
            0.45,
            0.45,
            0.45
        ],

        filename:
            "tripora-travel-plan.pdf",

        image: {
            type: "jpeg",

            quality: 0.98
        },

        html2canvas: {
            scale: 2,

            useCORS: true,

            backgroundColor: "#ffffff",

            logging: false
        },

        jsPDF: {
            unit: "in",

            format: "a4",

            orientation: "portrait"
        },

        pagebreak: {
            mode: [
                "css",
                "legacy"
            ]
        }
    };


    html2pdf()
        .set(options)
        .from(pdfContent)
        .save()

        .then(() => {

            downloadButton.innerHTML =
                originalHTML;

            downloadButton.disabled =
                false;

        })

        .catch((error) => {

            console.error(
                "PDF generation failed:",
                error
            );

            downloadButton.innerHTML =
                originalHTML;

            downloadButton.disabled =
                false;

            showError(
                "Could not generate the PDF."
            );
        });
}


/* ============================================================
   NEW TRIP
============================================================ */

function startNewTrip() {

    const hasCurrentTrip =
        currentThreadId ||
        latestAnswerMarkdown ||
        userInput.value.trim();


    if (hasCurrentTrip) {

        const confirmed =
            window.confirm(
                "Start a new trip? Your current conversation will remain saved in PostgreSQL, but this browser session will switch to a new thread."
            );


        if (!confirmed) {
            return;
        }
    }


    currentThreadId = null;

    latestAnswerMarkdown = "";


    localStorage.removeItem(
        "travel_thread_id"
    );


    userInput.value = "";

    updateCharacterCount();

    resultBox.innerHTML = "";

    threadInfo.textContent = "-";

    resultSection.classList.add(
        "hidden"
    );

    hideError();

    userInput.focus();


    window.scrollTo({
        top: 0,

        behavior: "smooth"
    });
}


/* ============================================================
   KEYBOARD SHORTCUT
============================================================ */

document.addEventListener(
    "keydown",
    function (event) {

        /*
         Ctrl + Enter
         or
         Cmd + Enter on Mac
        */

        if (
            (event.ctrlKey ||
                event.metaKey) &&
            event.key === "Enter"
        ) {

            event.preventDefault();

            sendMessage();
        }
    }
);


/* ============================================================
   INPUT EVENTS
============================================================ */

userInput.addEventListener(
    "input",
    updateCharacterCount
);


userInput.addEventListener(
    "keydown",
    function (event) {

        /*
         Enter = newline

         Ctrl/Cmd + Enter =
         submit request
        */

        if (
            (event.ctrlKey ||
                event.metaKey) &&
            event.key === "Enter"
        ) {

            event.preventDefault();

            sendMessage();
        }
    }
);


/* ============================================================
   NEW TRIP BUTTON
============================================================ */

newTripBtn.addEventListener(
    "click",
    startNewTrip
);


/* ============================================================
   INITIALIZATION
============================================================ */

updateCharacterCount();


/*
    If the user already has a thread,
    keep it silently in localStorage.

    This means:

        browser
            ↓
        thread_id
            ↓
        FastAPI
            ↓
        LangGraph
            ↓
        PostgreSQL

    The backend remains completely unchanged.
*/

if (currentThreadId) {

    threadInfo.textContent =
        currentThreadId;
}