package com.gudu.chat

import android.annotation.SuppressLint
import android.app.DownloadManager
import android.content.Context
import android.content.Intent
import android.graphics.Bitmap
import android.net.Uri
import android.os.Bundle
import android.os.Environment
import android.provider.MediaStore
import android.webkit.CookieManager
import android.webkit.DownloadListener
import android.webkit.JavascriptInterface
import android.webkit.ValueCallback
import android.webkit.WebChromeClient
import android.webkit.WebResourceError
import android.webkit.WebResourceRequest
import android.webkit.WebResourceResponse
import android.webkit.WebSettings
import android.webkit.WebView
import android.webkit.WebViewClient
import android.widget.Toast
import androidx.activity.OnBackPressedCallback
import androidx.activity.result.contract.ActivityResultContracts
import androidx.appcompat.app.AppCompatActivity
import androidx.core.content.ContextCompat
import androidx.core.content.FileProvider
import androidx.core.splashscreen.SplashScreen.Companion.installSplashScreen
import com.gudu.chat.databinding.ActivityMainBinding
import java.io.File

class MainActivity : AppCompatActivity() {

    private lateinit var binding: ActivityMainBinding
    private var uploadCallback: ValueCallback<Array<Uri>>? = null
    private var cameraImageUri: Uri? = null
    private var lastBackPress = 0L
    private var isGenerating = false
    private var isInBackground = false
    private var wasGeneratingInBackground = false

    private val fileChooserLauncher = registerForActivityResult(
        ActivityResultContracts.StartActivityForResult()
    ) { result ->
        val callback = uploadCallback ?: return@registerForActivityResult
        uploadCallback = null

        if (result.resultCode != RESULT_OK) {
            callback.onReceiveValue(null)
            return@registerForActivityResult
        }

        val data = result.data
        val uris = mutableListOf<Uri>()

        data?.clipData?.let { clipData ->
            for (i in 0 until clipData.itemCount) {
                uris.add(clipData.getItemAt(i).uri)
            }
        }

        data?.data?.let { uris.add(it) }
        cameraImageUri?.let { if (uris.isEmpty()) uris.add(it) }

        callback.onReceiveValue(if (uris.isEmpty()) null else uris.toTypedArray())
    }

    @SuppressLint("SetJavaScriptEnabled")
    override fun onCreate(savedInstanceState: Bundle?) {
        installSplashScreen()
        super.onCreate(savedInstanceState)
        binding = ActivityMainBinding.inflate(layoutInflater)
        setContentView(binding.root)

        setupWebView()
        setupRetry()
        setupBackPress()

        binding.webView.loadUrl(HOME_URL)
    }

    override fun onStart() {
        super.onStart()
        isInBackground = false
        wasGeneratingInBackground = false
        stopKeepAliveService()
    }

    override fun onStop() {
        super.onStop()
        isInBackground = true
        if (isGenerating) {
            startKeepAliveService(getString(R.string.notify_generating))
        }
    }

    private fun setupRetry() {
        binding.btnRetry.setOnClickListener {
            binding.errorLayout.visibility = android.view.View.GONE
            binding.webView.visibility = android.view.View.VISIBLE
            binding.webView.reload()
        }
    }

    @SuppressLint("SetJavaScriptEnabled", "JavascriptInterface")
    private fun setupWebView() {
        with(binding.webView.settings) {
            javaScriptEnabled = true
            domStorageEnabled = true
            allowFileAccess = true
            allowContentAccess = true
            mixedContentMode = WebSettings.MIXED_CONTENT_ALWAYS_ALLOW
            useWideViewPort = true
            loadWithOverviewMode = true
            setSupportZoom(false)
            userAgentString = "$userAgentString GuDuApp/1.0"
            cacheMode = WebSettings.LOAD_DEFAULT
            databaseEnabled = true
        }

        binding.webView.addJavascriptInterface(GenerateBridge(), "GuDuNative")

        CookieManager.getInstance().apply {
            setAcceptCookie(true)
            setAcceptThirdPartyCookies(binding.webView, true)
            flush()
        }

        binding.webView.webViewClient = object : WebViewClient() {
            override fun onPageStarted(view: WebView?, url: String?, favicon: Bitmap?) {
                super.onPageStarted(view, url, favicon)
                binding.errorLayout.visibility = android.view.View.GONE
                binding.webView.visibility = android.view.View.VISIBLE
            }

            override fun onPageFinished(view: WebView?, url: String?) {
                super.onPageFinished(view, url)
                injectGenerateObserver()
            }

            override fun onReceivedError(
                view: WebView?,
                request: WebResourceRequest?,
                error: WebResourceError?
            ) {
                if (request?.isForMainFrame == true) {
                    showErrorPage("网络连接失败，请检查网络后重试")
                }
            }

            override fun onReceivedHttpError(
                view: WebView?,
                request: WebResourceRequest?,
                errorResponse: WebResourceResponse?
            ) {
                if (request?.isForMainFrame == true && (errorResponse?.statusCode ?: 200) >= 400) {
                    showErrorPage("服务器异常，请稍后重试")
                }
            }
        }

        binding.webView.webChromeClient = object : WebChromeClient() {
            override fun onShowFileChooser(
                webView: WebView?,
                filePathCallback: ValueCallback<Array<Uri>>?,
                fileChooserParams: FileChooserParams?
            ): Boolean {
                uploadCallback?.onReceiveValue(null)
                uploadCallback = filePathCallback

                val contentIntent = Intent(Intent.ACTION_GET_CONTENT).apply {
                    addCategory(Intent.CATEGORY_OPENABLE)
                    type = "*/*"
                    putExtra(Intent.EXTRA_ALLOW_MULTIPLE, true)
                }

                val cameraIntent = Intent(MediaStore.ACTION_IMAGE_CAPTURE).apply {
                    cameraImageUri = createImageUri()
                    if (cameraImageUri != null) {
                        putExtra(MediaStore.EXTRA_OUTPUT, cameraImageUri)
                        addFlags(Intent.FLAG_GRANT_WRITE_URI_PERMISSION)
                        addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION)
                    }
                }
                val chooser = Intent.createChooser(contentIntent, "选择文件").apply {
                    putExtra(Intent.EXTRA_INITIAL_INTENTS, arrayOf(cameraIntent))
                }

                fileChooserLauncher.launch(chooser)
                return true
            }
        }

        binding.webView.setDownloadListener(DownloadListener { url, userAgent, contentDisposition, mimeType, _ ->
            val request = DownloadManager.Request(Uri.parse(url)).apply {
                setMimeType(mimeType)
                addRequestHeader("User-Agent", userAgent)
                setDescription("下载中...")
                setTitle(guessFileName(contentDisposition, mimeType))
                setNotificationVisibility(DownloadManager.Request.VISIBILITY_VISIBLE_NOTIFY_COMPLETED)
                setDestinationInExternalPublicDir(Environment.DIRECTORY_DOWNLOADS, guessFileName(contentDisposition, mimeType))
            }
            val dm = getSystemService(Context.DOWNLOAD_SERVICE) as DownloadManager
            dm.enqueue(request)
            Toast.makeText(this, "已开始下载", Toast.LENGTH_SHORT).show()
        })
    }

    private fun injectGenerateObserver() {
        val js = """
            (function() {
              if (window.__gudu_bg_installed) return;
              window.__gudu_bg_installed = true;

              function report() {
                try {
                  var thinking = !!document.querySelector('.thinking');
                  var sending = !!document.querySelector('#send-btn.stop');
                  var active = !!(thinking || sending);
                  if (window.GuDuNative && window.GuDuNative.onGenerationState) {
                    window.GuDuNative.onGenerationState(active);
                  }
                } catch (e) {}
              }

              var obs = new MutationObserver(function() { report(); });
              obs.observe(document.body, { childList: true, subtree: true, attributes: true });
              report();
              setInterval(report, 2000);
            })();
        """.trimIndent()
        binding.webView.evaluateJavascript(js, null)
    }

    private inner class GenerateBridge {
        @JavascriptInterface
        fun onGenerationState(active: Boolean) {
            runOnUiThread {
                isGenerating = active
                if (isInBackground && active) {
                    wasGeneratingInBackground = true
                    startKeepAliveService(getString(R.string.notify_generating))
                }
                if (!active) {
                    if (wasGeneratingInBackground) {
                        completeKeepAliveService(getString(R.string.notify_done))
                        wasGeneratingInBackground = false
                    } else {
                        stopKeepAliveService()
                    }
                }
            }
        }
    }

    private fun startKeepAliveService(text: String) {
        val intent = ForegroundKeepAliveService.startIntent(this, text)
        ContextCompat.startForegroundService(this, intent)
    }

    private fun stopKeepAliveService() {
        startService(ForegroundKeepAliveService.stopIntent(this))
    }

    private fun completeKeepAliveService(text: String) {
        startService(ForegroundKeepAliveService.completeIntent(this, text))
    }

    private fun createImageUri(): Uri? {
        return try {
            val image = File.createTempFile("gudu_camera_", ".jpg", cacheDir)
            FileProvider.getUriForFile(this, "${packageName}.fileprovider", image)
        } catch (_: Exception) {
            null
        }
    }

    private fun showErrorPage(message: String) {
        binding.errorMessage.text = message
        binding.webView.visibility = android.view.View.GONE
        binding.errorLayout.visibility = android.view.View.VISIBLE
    }

    private fun setupBackPress() {
        onBackPressedDispatcher.addCallback(this, object : OnBackPressedCallback(true) {
            override fun handleOnBackPressed() {
                if (binding.webView.canGoBack()) {
                    binding.webView.goBack()
                    return
                }
                val now = System.currentTimeMillis()
                if (now - lastBackPress < 2000) {
                    finish()
                } else {
                    lastBackPress = now
                    Toast.makeText(this@MainActivity, "再按一次退出", Toast.LENGTH_SHORT).show()
                }
            }
        })
    }

    private fun guessFileName(contentDisposition: String?, mimeType: String?): String {
        val byHeader = contentDisposition
            ?.split("filename=")
            ?.lastOrNull()
            ?.trim('"', '\'', ' ')
        if (!byHeader.isNullOrBlank()) return byHeader
        val ext = when {
            mimeType?.contains("pdf") == true -> "pdf"
            mimeType?.contains("png") == true -> "png"
            mimeType?.contains("jpeg") == true -> "jpg"
            else -> "bin"
        }
        return "gudu_${System.currentTimeMillis()}.$ext"
    }

    override fun onPause() {
        super.onPause()
        CookieManager.getInstance().flush()
    }

    companion object {
        private const val HOME_URL = "http://140.143.185.247:8100"
    }
}
