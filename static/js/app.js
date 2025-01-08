document.addEventListener("DOMContentLoaded", () => {
  let selectedPersona = "Helpful";

  document.querySelectorAll(".persona-button").forEach((button) => {
    button.addEventListener("click", () => {
      selectedPersona = button.getAttribute("data-persona");
      document.querySelectorAll(".persona-button img").forEach((img) => {
        img.classList.remove("selected");
      });
      button.querySelector("img").classList.add("selected");
    });
  });

  document.getElementById("send-button").addEventListener("click", async () => {
    const question = document.getElementById("question-input").value;
    if (!question.trim()) return;

    const responseElement = document.getElementById("chat-response");
    responseElement.innerHTML = "Loading...";

    try {
      const response = await fetch("/ask", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ question, persona: selectedPersona }),
      });

      const data = await response.json();
      if (data.answer) {
        responseElement.innerHTML = `<strong>Answer:</strong> ${data.answer}`;
      } else {
        responseElement.innerHTML = `<strong>Error:</strong> ${data.error}`;
      }
    } catch (error) {
      responseElement.innerHTML = "Failed to fetch answer.";
    }
  });
});
