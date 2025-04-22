/**
 * Handles model fetching and deployment for deploy.html.
 * Optional (commented) section for upload handling on index.html.
 */
document.addEventListener('DOMContentLoaded', () => {
    // --- Elements for Deployment Page (deploy.html) ---
    const modelList = document.getElementById('model-list');
    const loadingIndicator = document.getElementById('loading-models');
    const deployStatusDiv = document.getElementById('deploy-status');

    // --- Fetch and render models ---
    async function fetchModels() {
        const modelsApiUrl = '/api/models';

        if (loadingIndicator) loadingIndicator.style.display = 'block';
        if (modelList) modelList.innerHTML = '';
        hideStatusMessage();

        try {
            const response = await fetch(modelsApiUrl);
            if (!response.ok) {
                let errorMsg = `HTTP error! Status: ${response.status}`;
                try {
                    const errorData = await response.json();
                    errorMsg = errorData.message || errorData.error || errorMsg;
                } catch (_) {}
                throw new Error(errorMsg);
            }

            const models = await response.json();
            renderModelList(models);

        } catch (error) {
            console.error('Error fetching models:', error);
            if (modelList) {
                modelList.innerHTML = '<li style="color: #dc3545; text-align: center; padding: 15px;">Error loading models. Please try refreshing.</li>';
            }
            showStatusMessage(`Failed to fetch models: ${error.message}`, 'error');
        } finally {
            if (loadingIndicator) loadingIndicator.style.display = 'none';
        }
    }

    function renderModelList(models) {
        if (!modelList) return;

        modelList.innerHTML = '';
        if (!models || models.length === 0) {
            modelList.innerHTML = '<li style="text-align: center; padding: 15px;">No processed models found. Upload a model first.</li>';
            return;
        }

        models.forEach(model => {
            const listItem = document.createElement('li');
            listItem.setAttribute('data-model-id', model.id);

            const modelNameSpan = document.createElement('span');
            modelNameSpan.textContent = `${model.name || 'Unnamed Model'} (ID: ${model.id})`;

            const deployButton = document.createElement('button');
            deployButton.textContent = 'Deploy';
            deployButton.classList.add('btn', 'deploy-btn');
            deployButton.addEventListener('click', () => handleDeploy(model.id, model.name));

            listItem.appendChild(modelNameSpan);
            listItem.appendChild(deployButton);
            modelList.appendChild(listItem);
        });
    }

    async function handleDeploy(modelId, modelName) {
        console.log(`Deploying model: ${modelId}`);
        showStatusMessage(`Initiating deployment for model: ${modelName || modelId}...`, 'info');

        const deployApiUrl = '/api/deploy';

        try {
            const response = await fetch(deployApiUrl, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    // Add other headers like Authorization here if needed
                },
                body: JSON.stringify({ modelId }),
            });

            if (!response.ok) {
                let errorMsg = `Deployment failed! Status: ${response.status}`;
                try {
                    const errorData = await response.json();
                    errorMsg = errorData.message || errorData.error || errorMsg;
                } catch (_) {}
                throw new Error(errorMsg);
            }

            const result = await response.json();
            console.log('Deployment response:', result);

            showStatusMessage(`Successfully initiated deployment for ${modelName || modelId}. ${result.message || ''}`, 'success');

        } catch (error) {
            console.error('Deployment error:', error);
            showStatusMessage(`Error deploying model ${modelName || modelId}: ${error.message}`, 'error');
        }
    }

    function showStatusMessage(message, type = 'info') {
        if (!deployStatusDiv) return;
        deployStatusDiv.textContent = message;
        deployStatusDiv.className = `status-message ${type}`;
        deployStatusDiv.style.display = 'block';
    }

    function hideStatusMessage() {
        if (!deployStatusDiv) return;
        deployStatusDiv.style.display = 'none';
        deployStatusDiv.textContent = '';
        deployStatusDiv.className = 'status-message';
    }

    // --- Init ---
    if (modelList) {
        fetchModels();
    }

    // Upload section intentionally removed. Let me know if you want it uncommented and modularized.
});
