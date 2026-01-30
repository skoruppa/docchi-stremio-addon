function copy_to_clipboard() {
    /* Get the text field */
    let copyText = document.getElementById("manifest_url");

    /* Select the text field */
    copyText.setSelectionRange(0, copyText.value.length); /* For mobile devices */

    /* Copy the text inside the text field */
    try {
        navigator.clipboard.writeText(copyText.value).then(() => showToast("Skopiowano URL manifestu do schowka"));
    } catch (Exception) {
        try {
            // noinspection JSDeprecatedSymbols
            document.execCommand('copy')
            showToast("Skopiowano URL manifestu do schowka");
        } catch (Exception) {
            showToast("Nie udało się skopiować do schowka");
        }
    }
}

function showToast(message) {
    const toast = document.getElementById('toast');
    const toastMessage = document.getElementById('toast-message');
    toastMessage.textContent = message;
    toast.classList.add('show');
    setTimeout(() => {
        toast.classList.remove('show');
    }, 3000);
}

function toast() {
    /* Get the snackbar DIV */
    let x = document.getElementById("toast");
    x.show();
}
