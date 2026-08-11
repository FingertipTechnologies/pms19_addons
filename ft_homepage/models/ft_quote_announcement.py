# -*- coding: utf-8 -*-
import re
from urllib.parse import quote, urlparse

from odoo import _, api, fields, models
from odoo.exceptions import AccessError, ValidationError

# Matches the src="..." of a pasted <iframe> embed snippet (e.g. LinkedIn's
# own "Embed this post" code). Falls back to treating the whole input as a
# plain URL when no <iframe> is found.
_IFRAME_SRC_RE = re.compile(r'<iframe[^>]*\bsrc=["\']([^"\']+)["\']', re.IGNORECASE)

# Exact-match allowlist of hosts we'll render as an iframe. Exact match
# (not endswith/substring) so "linkedin.com.evil.example" can't sneak in.
_SOCIAL_EMBED_HOSTS = {
    "linkedin": {"www.linkedin.com", "linkedin.com"},
    "facebook": {"www.facebook.com", "facebook.com"},
}

# Everything that is not text. These are the entries laid out as cards in the
# Homepage footer; text is handled separately and goes to the panel instead.
MEDIA_CONTENT_TYPES = ("image", "video", "social")

# At most four media entries may be active at once. The footer lays the cards
# out on a grid with a track per card (see quote_widget.scss) and stops having
# a sensible arrangement past four — a fifth would either shrink every card
# below a readable width or silently never be shown.
MAX_ACTIVE_MEDIA = 4

# At most one text entry may be active at once. All text is displayed in the
# upper-right panel whatever its kind, and that panel is sized for a single
# block of text beside the app icons.
MAX_ACTIVE_TEXT = 1

# Longest text that fits the upper-right panel without being clipped or
# pushing the panel past the app-icon grid.
#
# Derived from the panel's own geometry rather than picked at random: the panel
# caps at 360px wide with 16px of padding each side, leaving 328px of content.
# At its 0.95rem font that is roughly 43 characters a line, and 300 characters
# is therefore about seven lines — near 165px of text, comfortably inside the
# panel's 420px body even once the contributor line is added.
#
# Change this and the CSS together: the whole point of the limit is that no
# text long enough to overflow can be saved in the first place, which is what
# lets the panel drop the line-clamp that used to truncate quotes mid-sentence.
# The form view repeats the number as the ft_limited_text widget's max_length
# (and in its placeholder) to stop the typing at the cap — keep the two in step.
TEXT_MAX_LENGTH = 300


class FtQuoteAnnouncement(models.Model):
    _name = "ft.quote.announcement"
    _description = "Quote of the Day / Announcement"
    _order = "sequence, date_from desc, id desc"
    _rec_name = "title"

    title = fields.Char(
        string="Title",
        required=True,
        help="Internal label, e.g. 'Quote of the Day - 20 Jul' or "
        "'Org Announcement - Holiday List'.",
    )
    sequence = fields.Integer(default=10)
    # Entries start INACTIVE: anyone may add one, but it only appears on the
    # Homepage once HR / an Admin activates it (see create/write below).
    active = fields.Boolean(default=False)

    content_type = fields.Selection(
        [
            ("text", "Text"),
            ("image", "Image"),
            ("video", "Video"),
            ("social", "HTML (LinkedIn / Facebook embed)"),
        ],
        string="Content Type",
        required=True,
        default="text",
    )

    # Text content — rendered with decorative quotation-mark styling in the
    # upper-right panel, whatever `kind` the entry carries.
    text_content = fields.Text(
        string="Quote / Announcement Text",
        help="Shown in the panel beside the app icons. Limited to %d "
        "characters so it always fits without being cut off." % TEXT_MAX_LENGTH,
    )

    # Image content
    image = fields.Image(string="Image", max_width=1920, max_height=1080)

    # Video content — either an uploaded file or an external URL
    # (e.g. YouTube / Vimeo / an internal .mp4 link).
    video_url = fields.Char(
        string="Video URL",
        help="Link to a video (YouTube, Vimeo, or a direct .mp4 URL).",
    )
    video_file = fields.Binary(
        string="Upload Video",
        attachment=True,
        help="Upload a video file (.mp4/.webm) directly instead of "
        "providing a URL. If both are set, the uploaded file is used.",
    )
    video_filename = fields.Char(string="Video Filename")

    # Social media content — accepts EITHER a plain public post URL, OR the
    # full <iframe> embed code copied from the platform's own "Embed this
    # post" feature (recommended — see _ft_resolve_social_embed). Text, not
    # Char: a pasted embed snippet can be long.
    social_url = fields.Text(
        string="Post URL or Embed Code",
        help="For a reliable embed, use the platform's own \"Embed\" / "
        "\"Embed this post\" option (on the post's ••• menu) and paste the "
        "WHOLE <iframe> code here, e.g.:\n"
        '<iframe src="https://www.linkedin.com/embed/feed/update/'
        'urn:li:share:XXXXXXXXXXXX" height="600" width="504"></iframe>\n\n'
        "A plain post URL also works but is less reliable to auto-embed.",
    )

    contributor_id = fields.Many2one(
        "res.users",
        string="Contributed By",
        help="Shown alongside the quote/announcement on the Homepage.",
    )
    contributor_name = fields.Char(
        string="Contributor Name (override)",
        help="Use this to show a name that isn't an Odoo user "
        "(e.g. a client or a founder). Overrides 'Contributed By' if set.",
    )

    date_from = fields.Date(string="Show From", default=fields.Date.context_today)
    date_to = fields.Date(string="Show Until")

    kind = fields.Selection(
        [
            ("quote", "Quote of the Day"),
            ("announcement", "Announcement"),
            ("update", "Org-wide Update"),
        ],
        default="quote",
        required=True,
    )

    def _ft_resolve_social_embed(self):
        """Turn whatever was pasted into `social_url` — a plain post URL, or
        a full <iframe> embed snippet copied from the platform's own "Embed"
        feature — into a validated iframe `src` safe to render on the
        Homepage for every user.

        Returns (src, platform) on success, e.g.
        ("https://www.linkedin.com/embed/feed/update/urn:li:share:123",
         "linkedin"), or (False, False) if nothing usable/safe was found.

        Security: the resolved src's host must be an EXACT match against
        `_SOCIAL_EMBED_HOSTS` (not endswith/substring — that would let e.g.
        "linkedin.com.evil.example" slip through) and scheme must be https.
        This is what actually gates what can render as an iframe on the
        Homepage — content_type='social' entries always go through this
        before display, however they were entered.
        """
        self.ensure_one()
        raw = (self.social_url or "").strip()
        if not raw:
            return False, False

        match = _IFRAME_SRC_RE.search(raw)
        src = match.group(1) if match else raw

        parsed = urlparse(src)
        if parsed.scheme != "https":
            return False, False
        host = parsed.netloc.lower()

        if host in _SOCIAL_EMBED_HOSTS["linkedin"]:
            # Already an embeddable URL (from a pasted <iframe> or an /embed/
            # link)? Use it directly.
            if "/embed/" in parsed.path:
                return src, "linkedin"
            # A plain LinkedIn post/feed URL CANNOT be iframed — post pages
            # send X-Frame-Options: DENY, so the iframe just renders blank /
            # broken. Rebuild the embeddable /embed/feed/update/ URL from the
            # numeric activity (or legacy share) id carried in the link, e.g.
            #   .../posts/..-activity-7123456789012345678-AbCd/  or
            #   .../feed/update/urn:li:activity:7123456789012345678
            id_match = re.search(r"(?:activity|share)[:\-](\d+)", src)
            if id_match:
                kind = "share" if ("share" in src and "activity" not in src) else "activity"
                return (
                    "https://www.linkedin.com/embed/feed/update/urn:li:%s:%s"
                    % (kind, id_match.group(1)),
                    "linkedin",
                )
            # A LinkedIn link with no usable id can't be embedded.
            return False, False

        if host in _SOCIAL_EMBED_HOSTS["facebook"]:
            # Facebook's Post Plugin needs the ORIGINAL post URL wrapped in
            # a plugins/post.php iframe; if the user already pasted that
            # plugin URL directly (host is still facebook.com), use it as-is.
            if "/plugins/post.php" in parsed.path:
                return src, "facebook"
            return (
                "https://www.facebook.com/plugins/post.php?href=%s&show_text=true&width=500"
                % quote(src, safe=""),
                "facebook",
            )

        return False, False

    @api.constrains(
        "content_type", "text_content", "image", "video_url", "video_file",
        "social_url",
    )
    def _check_content_matches_type(self):
        for rec in self:
            if rec.content_type == "text" and not rec.text_content:
                raise ValidationError("Please add the quote/announcement text.")
            if rec.content_type == "image" and not rec.image:
                raise ValidationError("Please upload an image.")
            if rec.content_type == "video" and not (rec.video_url or rec.video_file):
                raise ValidationError(
                    "Please upload a video file or provide a video URL."
                )
            if rec.content_type == "social":
                if not rec.social_url:
                    raise ValidationError(
                        "Please paste a LinkedIn or Facebook post URL or embed code."
                    )
                src, _platform = rec._ft_resolve_social_embed()
                if not src:
                    raise ValidationError(
                        "That doesn't look like a public LinkedIn or Facebook "
                        "link/embed code. Use the post's ••• menu → \"Embed\" "
                        "/ \"Embed this post\" and paste the whole <iframe> "
                        "code, or a plain https://linkedin.com or "
                        "https://facebook.com post link."
                    )

    @api.constrains("content_type", "text_content")
    def _check_text_length(self):
        """Keep text short enough that the panel never has to truncate it.

        Enforced on save rather than trimmed at display time on purpose: a
        limit the author is told about while writing is the only version of
        this that prevents a half-sentence appearing on everybody's Homepage.
        """
        for rec in self:
            if rec.content_type != "text":
                continue
            length = len(rec.text_content or "")
            if length > TEXT_MAX_LENGTH:
                raise ValidationError(
                    _(
                        "The text is %(length)s characters long, which is more "
                        "than the %(limit)s that fit the Homepage panel. Please "
                        "shorten it by %(excess)s characters.",
                        length=length,
                        limit=TEXT_MAX_LENGTH,
                        excess=length - TEXT_MAX_LENGTH,
                    )
                )

    def _ft_count_active(self, content_types):
        """How many entries of these content types are live right now.

        active_test=False so the search is not silently narrowed to active
        records before the domain is applied — the domain says which state we
        are counting, and being explicit is what keeps this readable.
        """
        return self.with_context(active_test=False).search_count(
            [("active", "=", True), ("content_type", "in", list(content_types))]
        )

    @api.constrains("active", "content_type")
    def _check_active_limits(self):
        """Cap what may be live at once: 4 media entries, 1 text entry.

        Checked against the whole table rather than just `self`, because the
        limit is a property of the Homepage as a whole. Runs after the write,
        so the counts already include whatever is being activated.

        Only worth checking when something is actually being switched on —
        deactivating can never breach a maximum.
        """
        if not any(rec.active for rec in self):
            return

        media_count = self._ft_count_active(MEDIA_CONTENT_TYPES)
        if media_count > MAX_ACTIVE_MEDIA:
            raise ValidationError(
                _(
                    "Only %(limit)s media entries (Image / Video / HTML) can be "
                    "active at a time, and there are now %(count)s. Please "
                    "deactivate one before activating another.",
                    limit=MAX_ACTIVE_MEDIA,
                    count=media_count,
                )
            )

        text_count = self._ft_count_active(["text"])
        if text_count > MAX_ACTIVE_TEXT:
            raise ValidationError(
                _(
                    "Only %(limit)s text entry can be active at a time, and "
                    "there are now %(count)s. Please deactivate the current one "
                    "before activating another.",
                    limit=MAX_ACTIVE_TEXT,
                    count=text_count,
                )
            )

    def _ft_user_can_activate(self):
        """Only HR users, Admins (and system/sudo calls) may publish
        (activate/deactivate) a quote or announcement."""
        return (
            self.env.su
            or self.env.user.has_group("hr.group_hr_user")
            or self.env.user.has_group("base.group_system")
        )

    @api.model_create_multi
    def create(self, vals_list):
        # Anyone can add an entry, but non-HR/Admin users cannot create it
        # already-active — it must be activated by HR/Admin afterwards.
        if not self._ft_user_can_activate():
            for vals in vals_list:
                vals["active"] = False
        return super().create(vals_list)

    def write(self, vals):
        if "active" in vals and not self._ft_user_can_activate():
            raise AccessError(
                _(
                    "Only HR or an Administrator can activate or deactivate a "
                    "quote / announcement."
                )
            )
        return super().write(vals)

    @api.model
    def get_homepage_content(self):
        """Return ALL active quotes/announcements to show on the Homepage
        right now (respecting the optional Show From / Show Until window),
        ordered by priority. E.g. a text Quote of the Day AND a video
        announcement that are both active are BOTH returned and displayed.
        """
        # sudo(): the homepage widget must work for EVERY logged-in user,
        # regardless of their access rights on this backend model.
        records = self.sudo()
        today = fields.Date.context_today(self)
        domain = [
            "|",
            ("date_from", "=", False),
            ("date_from", "<=", today),
        ]
        domain += [
            "|",
            ("date_to", "=", False),
            ("date_to", ">=", today),
        ]
        items = []
        for record in records.search(domain):
            contributor = record.contributor_name or record.contributor_id.name or ""
            social_src, social_platform = (
                record._ft_resolve_social_embed()
                if record.content_type == "social"
                else (False, False)
            )
            items.append({
                "id": record.id,
                "title": record.title,
                "kind": record.kind,
                "content_type": record.content_type,
                "text_content": record.text_content,
                # Inline base64 data URI instead of a /web/image URL, so
                # the image displays for every user without needing read
                # access to the model at the HTTP image route.
                "image_url": (
                    "data:image/png;base64,%s" % record.image.decode()
                    if record.content_type == "image" and record.image
                    else False
                ),
                # Uploaded video file wins over the URL; it is streamed
                # through our own sudo'd controller so every user can
                # play it.
                "video_src": (
                    "/ft_homepage/video/%s" % record.id
                    if record.content_type == "video" and record.video_file
                    else False
                ),
                "video_url": (
                    record.video_url if record.content_type == "video" else False
                ),
                "social_embed_src": social_src,
                "social_platform": social_platform,
                # Fallback link shown when the post can't be embedded (e.g. the
                # user pasted a profile/company page instead of a single post).
                # Only expose a plain https link, never a raw <iframe> snippet.
                "social_link": (
                    record.social_url.strip()
                    if record.content_type == "social"
                    and record.social_url
                    and record.social_url.strip().startswith("https://")
                    else False
                ),
                "contributor": contributor,
            })
        return items
