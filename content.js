(() => {
    // Prevent duplicate injection
    if (window.focusBullyInitialized) return;
    window.focusBullyInitialized = true;

    const CLOSE_BUTTON_TEXTS = [
        'Keep roasting me',
        'Born to be roasted by Machine',
        'I deserve this',
        'Okay, I am back to work',
        'Bully me more'
    ];

    let shadowRoot = null;

    function createPopup(data) {
        // Create Host
        let host = document.getElementById('focus-bully-host');
        if (!host) {
            host = document.createElement('div');
            host.id = 'focus-bully-host';
            document.body.appendChild(host);
            shadowRoot = host.attachShadow({ mode: 'open' });
        } else {
            shadowRoot = host.shadowRoot;
            shadowRoot.innerHTML = ''; // Clear previous popup to prevent stacking
        }

        // Add Styles
        const styleLink = document.createElement('link');
        styleLink.rel = 'stylesheet';
        styleLink.href = chrome.runtime.getURL('styles.css');
        shadowRoot.appendChild(styleLink);

        // Create Content
        const container = document.createElement('div');
        container.className = 'bully-container';
        
        const overlay = document.createElement('div');
        overlay.className = 'bully-overlay';

        const emoji = document.createElement('span');
        emoji.className = 'bully-emoji';
        emoji.textContent = data.emoji || '🤨';

        const roast = document.createElement('p');
        roast.className = 'bully-roast';
        roast.textContent = data.roast;

        const button = document.createElement('button');
        button.className = 'bully-button';
        button.textContent = CLOSE_BUTTON_TEXTS[Math.floor(Math.random() * CLOSE_BUTTON_TEXTS.length)];

        button.addEventListener('click', () => {
            container.classList.remove('visible');
            overlay.classList.remove('visible');
            setTimeout(() => {
                host.remove();
                window.focusBullyInitialized = false;
            }, 400);
        });

        container.appendChild(emoji);
        container.appendChild(roast);
        container.appendChild(button);
        
        shadowRoot.appendChild(overlay);
        shadowRoot.appendChild(container);

        // Trigger Animations
        requestAnimationFrame(() => {
            container.classList.add('visible');
            overlay.classList.add('visible');
        });
    }

    chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
        if (message.action === 'SHOW_ROAST') {
            createPopup(message.data);
        }
    });
})();
