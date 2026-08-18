# Fonts

Drop the font files here. Either `.woff2` or `.ttf` works — the `@font-face`
rules in `content.js` list both and the browser takes whichever exists.

Required filenames (exact, case-sensitive):

    EduNSWACTCursive-Bold.{woff2,ttf}   <- the "GreenSwap" wordmark
    EBGaramond-Regular.{woff2,ttf}      <- body text
    EBGaramond-SemiBold.{woff2,ttf}     <- product names, prices

Both families ship as variable fonts on Google Fonts. Take the fixed weights
from the `static/` folder inside each download — the file at the top level of
the zip is the variable one and will not match these names.

Both are OFL-licensed, so bundling them in the extension is fine. Keep the
OFL.txt from each download in this folder to satisfy the licence.

We bundle rather than loading from Google Fonts on purpose: a webfont request
fires on every product page a user opens, which is slow and hands their
browsing history to a third party. That is a bad trade for a tool whose whole
pitch is trustworthiness.
