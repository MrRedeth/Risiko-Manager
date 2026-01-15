const API_BASE = '/api';

/**
 * Shared Utils
 */
async function fetchAPI(endpoint, options = {}) {
    const res = await fetch(`${API_BASE}${endpoint}`, options);
    if (!res.ok) {
        const err = await res.json();
        throw new Error(err.error || 'Server Error');
    }
    return res.json();
}

function getAdminKey() {
    return localStorage.getItem('adminKey');
}

function formatRating(rating) {
    return Math.round(rating);
}

function formatDate(isoString) {
    return new Date(isoString).toLocaleDateString('it-IT', {
        day: 'numeric',
        month: 'short',
        year: 'numeric'
    });
}

function showToast(message, type = 'success') {
    // Simple toast implementation
    const toast = document.createElement('div');
    toast.style.position = 'fixed';
    toast.style.bottom = '20px';
    toast.style.right = '20px';
    toast.style.padding = '1rem 2rem';
    toast.style.background = type === 'error' ? 'rgba(239, 68, 68, 0.9)' : 'rgba(34, 197, 94, 0.9)';
    toast.style.color = 'white';
    toast.style.borderRadius = '8px';
    toast.style.backdropFilter = 'blur(4px)';
    toast.style.zIndex = '100';
    toast.innerHTML = message;
    document.body.appendChild(toast);
    setTimeout(() => toast.remove(), 3000);
}
