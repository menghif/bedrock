# coding=utf-8

# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""This library parses dotlang files migrated over from the old PHP
system.

It caches them using the django caching library, but it could
potentially just use thread-local variables. Caching seems safer at
the expense of another caching layer."""
import codecs
import inspect
import os
import re
from functools import partial

from django.conf import settings
from django.core.cache import caches
from django.utils.functional import lazy

from jinja2 import Markup
from product_details import product_details

from lib.l10n_utils import translation
from lib.l10n_utils.utils import ContainsEverything, strip_whitespace

ALL_THE_THINGS = ContainsEverything()
FORMAT_IDENTIFIER_RE = re.compile(
    r"""(%
                                      (?:\((\w+)\))? # Mapping key
                                      s)""",
    re.VERBOSE,
)
TAG_REGEX = re.compile(r"^## ([\w-]+) ##")
cache = caches["l10n"]


def _replace_variables(match):
    var_name = match[2]
    if not var_name:
        var_name = "VARIABLE_MISSING"

    return f"{{ ${var_name} }}"


def convert_variables(lang_str):
    return FORMAT_IDENTIFIER_RE.sub(_replace_variables, lang_str)


def parse(path, skip_untranslated=True, extract_comments=False):
    """
    Parse a dotlang file and return a dict of translations.
    :param path: Absolute path to a lang file.
    :param skip_untranslated: Exclude strings for which the ID and translation
                              match.
    :param extract_comments: Extract one line comments from template if True
    :return: dict
    """
    trans = {}

    if not os.path.exists(path):
        return trans

    with codecs.open(path, "r", "utf-8", errors="replace") as lines:
        source = None
        comment = None

        for line in lines:
            l10n_tag = None
            if "�" in line:
                mail_error(path, line)

            line = line.strip()
            if not line:
                continue

            if line[0] == "#":
                comment = line.lstrip("#").strip()
                continue

            if line[0] == ";":
                source = line[1:]
            elif source:
                for tag in ("{ok}", "{l10n-extra}"):
                    if line.lower().endswith(tag):
                        l10n_tag = tag.strip("{}")
                        line = line[: -len(tag)]
                line = line.strip()
                if skip_untranslated and source == line and l10n_tag != "ok":
                    continue
                if extract_comments:
                    trans[source] = [comment, line]
                    comment = None
                else:
                    trans[source] = line

    return trans


def mail_error(path, message):
    """Email managers when an error is detected"""
    from django.core import mail

    subject = "%s is corrupted" % path
    mail.mail_managers(subject, message)


def translate(text, files):
    """Search a list of .lang files for a translation"""
    lang = translation.get_language(True)

    # don't attempt to translate the default language.
    if lang == settings.LANGUAGE_CODE:
        return Markup(text)

    tweaked_text = strip_whitespace(text)

    for file_ in files:
        key = "dotlang-%s-%s" % (lang, file_)
        path = str(settings.LOCALES_PATH / lang / f"{file_}.lang")
        trans = cache.get(key)
        if trans is None:
            trans = parse(path)
            cache.set(key, trans)

        if tweaked_text in trans:
            original = FORMAT_IDENTIFIER_RE.findall(text)
            translated = FORMAT_IDENTIFIER_RE.findall(trans[tweaked_text])
            if set(original) != set(translated):
                explanation = "The translation has a different set of replaced text (aka %s)"
                message = "%s\n\n%s\n%s" % (explanation, text, trans[tweaked_text])
                mail_error(path, message)
                return Markup(text)
            return Markup(trans[tweaked_text])
    return Markup(text)


def _get_extra_lang_files():
    frame = inspect.currentframe()
    new_lang_files = []
    if frame is None:
        if settings.DEBUG:
            import warnings

            warnings.warn(
                "Your Python runtime does not support the frame stack. Extra LANG_FILES specified in Python source files will not work.",
                RuntimeWarning,
            )
    else:
        try:
            # gets value of LANG_FILE constant in calling module if specified.
            # have to go back 2x to compensate for this function.
            new_lang_files = frame.f_back.f_back.f_globals.get("LANG_FILES", [])
        finally:
            del frame
        if new_lang_files:
            if isinstance(new_lang_files, str):
                new_lang_files = [new_lang_files]
    return [lf for lf in new_lang_files if lf not in settings.DOTLANG_FILES]


def gettext(text, *args, **kwargs):
    """
    Translate a piece of text from the global files. If `LANG_FILES` is defined
    in the module from which this function is called, those files (or file)
    will be searched first for the translation, followed by the default files.

    :param text: string to translate
    :param args: items for interpolation into `text`
    :param lang_files: extra lang file names to search for a translation.
        NOTE: DO NOT USE THIS for string extraction. It will NOT respect
        the values in this kwarg when extracting strings. This is only useful
        if you know the string is in a different file but you don't want to
        add that file for the whole module via the `LANG_FILES` constant.
    :return: translated string
    """
    lang_files = kwargs.pop("lang_files", [])
    if isinstance(lang_files, list):
        lang_files = lang_files[:]
    else:
        lang_files = [lang_files]
    if not lang_files:
        lang_files += _get_extra_lang_files()
    lang_files += settings.DOTLANG_FILES

    text = translate(text, lang_files)
    if args:
        text = text % args
    return text


_lazy_proxy = lazy(gettext, str)


def gettext_lazy(*args, **kwargs):
    lang_files = _get_extra_lang_files()
    if lang_files:
        return partial(_lazy_proxy, lang_files=lang_files)(*args, **kwargs)
    return _lazy_proxy(*args, **kwargs)


# backward compat
_ = gettext
_lazy = gettext_lazy


def lang_file_is_active(path, lang=None):
    """
    If the lang file for a locale exists and has the correct comment returns
    True, and False otherwise.
    :param path: the relative lang file name
    :param lang: the language code
    :return: bool
    """
    return lang_file_has_tag(path, lang, "active")


def lang_file_tag_set(path, lang=None):
    """Return a set of tags for a specific lang file and locale.

    :param path: the relative lang file name
    :param lang: the language code or the lang of the request if omitted
    :return: set of strings
    """
    if settings.DEV or lang == settings.LANGUAGE_CODE:
        return ALL_THE_THINGS

    lang = lang or translation.get_language(True)
    fpath = settings.LOCALES_PATH / lang / f"{path}.lang"
    cache_key = f"tag:locale/{lang}/{path}.lang"
    tag_set = cache.get(cache_key)
    if tag_set is None:
        tag_set = set()
        try:
            with codecs.open(fpath, "r", "utf-8", errors="replace") as lines:
                for line in lines:
                    # Filter out Byte order Mark
                    line = line.replace("\ufeff", "")
                    m = TAG_REGEX.match(line)
                    if m:
                        tag_set.add(m.group(1))
                    else:
                        # Stop at the first non-tag line.
                        break
        except IOError:
            pass

        cache.set(cache_key, tag_set)

    return tag_set


def lang_file_has_tag(path, lang=None, tag="active"):
    """
    Return True if the lang file exists and has a line like "^## tag ##"
    at the top. Stops looking at the line that doesn't have a tag.

    Always returns true for the default lang.

    :param path: the relative lang file name
    :param lang: the language code or the lang of the request if omitted
    @param tag: The string that should appear between ##'s. Can contain
       alphanumerics and "_".
    @return: bool
    """
    return tag in lang_file_tag_set(path, lang)


def get_translations_for_langfile(langfile):
    """
    Return the list of available translations for the langfile.

    :param langfile: the path to a lang file, retrieved with get_l10n_path()
    :return: list, like ['en-US', 'fr']
    """

    cache_key = "translations:%s" % langfile
    translations = cache.get(cache_key, None)

    if translations:
        return translations

    translations = []
    for lang in settings.PROD_LANGUAGES:
        if lang in product_details.languages and (lang == settings.LANGUAGE_CODE or lang_file_is_active(langfile, lang)):
            translations.append(lang)

    cache.set(cache_key, translations)
    return translations


def get_translations_native_names(locales):
    """
    Return a dict of locale codes and native language name strings.

    Returned dict is suitable for use in view contexts and is filtered to only codes in PROD_LANGUAGES.

    :param locales: list of locale codes
    :return: dict, like {'en-US': 'English (US)', 'fr': 'Français'}
    """
    translations = {}
    for locale in locales:
        if locale in settings.PROD_LANGUAGES:
            language = product_details.languages.get(locale)
            translations[locale] = language["native"] if language else locale

    return translations
