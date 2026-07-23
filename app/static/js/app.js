// PBC 智能管理工作站 - M1 占位逻辑
// M3/M4 起接入拖拽上传 + AI 解析

document.addEventListener('DOMContentLoaded', () => {
    const dropzone = document.getElementById('dropzone');
    const fileInput = document.getElementById('fileInput');
    const status = document.getElementById('status');

    function handleFiles(files) {
        if (!files || files.length === 0) return;
        const formData = new FormData();
        for (const f of files) formData.append('files', f);
        fetch('/api/files/drag-drop', { method: 'POST', body: formData })
            .then(r => r.json())
            .then(d => {
                status.innerHTML = `<pre>${JSON.stringify(d, null, 2)}</pre>`;
            })
            .catch(e => status.innerHTML = `<p style="color:red">${e}</p>`);
    }

    fileInput.addEventListener('change', e => handleFiles(e.target.files));

    dropzone.addEventListener('dragover', e => { e.preventDefault(); dropzone.style.background = '#eef'; });
    dropzone.addEventListener('dragleave', e => { e.preventDefault(); dropzone.style.background = '#fff'; });
    dropzone.addEventListener('drop', e => {
        e.preventDefault();
        dropzone.style.background = '#fff';
        handleFiles(e.dataTransfer.files);
    });
});
