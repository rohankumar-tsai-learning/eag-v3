/**
 * Handles communication with the Google Gemini API.
 */
export async function getRoastFromGemini(apiKey, productiveContext, distractionTopic) {
    const endpoint = `https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent?key=${apiKey}`;
    
    const prompt = `You are a smart-aleck, judgmental but helpful focus coach.
The user was just on ${productiveContext.site} doing ${productiveContext.tasks || 'work'} and suddenly switched to ${distractionTopic.site} to look at "${distractionTopic.title}".
Roast them in one short, witty sentence. Be funny but ultimately tell them to get back to work. Mention why "${distractionTopic.title}" is a waste of time compared to ${productiveContext.site}.

Examples of the tone to use:
- 'Is the history of spoons really more important than your thesis, Rohan?'
- 'What are we doing here?'
- 'Yeah, this is what the world needs right now and You can definitely contribute to it?'
- 'You have a attention span of a fly?'
- 'Are you an octopus or lady that can handle multiple task at once?'

Output your response as a JSON object with two fields: "roast" (the text) and "emoji" (a matching judgey emoji).`;

    try {
        const response = await fetch(endpoint, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({
                contents: [{
                    parts: [{ text: prompt }]
                }],
                generationConfig: {
                    response_mime_type: "application/json"
                }
            })
        });

        if (!response.ok) {
            throw new Error(`Gemini API error: ${response.statusText}`);
        }

        const data = await response.json();
        const content = data.candidates[0].content.parts[0].text;
        return JSON.parse(content);
    } catch (error) {
        console.error("Failed to fetch roast:", error);
        return {
            roast: "I'd roast you, but your internet is as slow as your productivity.",
            emoji: "🐌"
        };
    }
}
