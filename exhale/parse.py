# -*- coding: utf8 -*-
########################################################################################
# This file is part of exhale.  Copyright (c) 2017, Stephen McDowell.                  #
# Full BSD 3-Clause license available here:                                            #
#                                                                                      #
#                     https://github.com/svenevs/exhale/LICENSE.md                     #
########################################################################################

from . import configs
from . import utils

import textwrap
from bs4 import BeautifulSoup

__all__       = ["getFileBriefAndDetailedRST"]
__name__      = "utils"
__docformat__ = "reStructuredText"


def walk(textRoot, currentTag, level, prefix=None, postfix=None, unwrapUntilPara=False):
    '''
    Recursive traverser method to parse the input parsed xml tree and convert the nodes
    into raw reStructuredText from the input doxygen format.  **Not all doxygen markup
    types are handled**, see ``todo`` at bottom of documentation for this method.  The
    current supported doxygen xml markup tags are:

    - ``para``
    - ``orderedlist``
    - ``itemizedlist``
    - ``verbatim``
        - ``embed:rst:leading-asterisk``
    - ``formula``
    - ``ref``

    The goal of this method is to "explode" input ``xml`` data into raw reStructuredText
    to put at the top of the file pages.  Wielding beautiful soup, this essentially
    means that you need to expand every non ``para`` tag into a ``para``.  So if an
    ordered list appears in the xml, then the raw listing must be built up from the
    child nodes.  After this is finished, though, the :func:`bs4.BeautifulSoup.get_text`
    method will happily remove all remaining ``para`` tags to produce the final
    reStructuredText **provided that** the original "exploded" tags (such as the ordered
    list definition and its ``listitem`` children) have been *removed* from the soup.

    :Parameters:
        ``textRoot`` (:class:`exhale.graph.ExhaleRoot`)
            The text root object that is calling this method.  This parameter is
            necessary in order to retrieve / convert the doxygen ``\ref SomeClass`` tag
            and link it to the appropriate node page.  The ``textRoot`` object is not
            modified by executing this method.

        ``currentTag`` (:class:`bs4.Tag`)
            The current xml tag being processed, either to have its contents directly
            modified or unraveled.

        ``level`` (int)
            The **block** level of indentation currently being parsed.  Because we are
            parsing a tree in order to generate raw reStructuredText code, we need to
            maintain a notion of "block level".  This means tracking when there are
            nested structures such as a list within a list:

            .. code-block:: rst

               1. This is an outer ordered list.

                   - There is a nested unordered list.
                   - It is a child of the outer list.

               2. This is another item in the outer list.

            The outer ordered (numbers ``1`` and ``2``) list is at indentation level
            ``0``, and the inner unordered (``-``) list is at indentation level ``1``.
            Meaning that level is used as

            .. code-block:: py

               indent = "    " * level
               # ... later ...
               some_text = "\n{indent}{text}".format(indent=indent, text=some_text)

            .. warning::

               This variable does **not** represent "recursion depth" (as one would
               typically see with a variable like this)!

    .. todo::

       This method does not cover all possible input doxygen types!  This means that
       when an unsupported / unrecognized doxygen tag appears in the xml listing, the
       **raw xml will appear on the file page being documented**.  This traverser is
       greedily designed to work for what testing revealed as the *bare minimum*
       required.  **Please** submit an issue with a new tag if you need one!  Adding
       them in is generally not difficult, but there were too many / I do not intend on
       reimplementing a doxygen xml parser --- that's what breathe is for.

       AKA this method only exists because I could not identify an easy way to extract
       this information from breathe.  This method will likely disappear if I ever do.
    '''
    if not currentTag:
        return

    if prefix:
        currentTag.insert_before(prefix)
    if postfix:
        currentTag.insert_after(postfix)

    children = currentTag.findChildren(recursive=False)
    indent = "   " * level
    if currentTag.name == "orderedlist":
        idx = 1
        for child in children:
            walk(textRoot, child, level + 1, "\n{}{}. ".format(indent, idx), None, True)
            idx += 1
            child.unwrap()
        currentTag.unwrap()
    elif currentTag.name == "itemizedlist":
        for child in children:
            walk(textRoot, child, level + 1, "\n{}- ".format(indent), None, True)
            child.unwrap()
        currentTag.unwrap()
    elif currentTag.name == "verbatim":
        # TODO: find relevant section in breathe.sphinxrenderer and include the versions
        #       for both leading /// as well as just plain embed:rst.
        leading_asterisk = "embed:rst:leading-asterisk\n*"
        if currentTag.string.startswith(leading_asterisk):
            cont = currentTag.string.replace(leading_asterisk, "")
            cont = textwrap.dedent(cont.replace("\n*", "\n"))
            currentTag.string = cont
    elif currentTag.name == "formula":
        currentTag.string = ":math:`{}`".format(currentTag.string[1:-1])
    elif currentTag.name == "ref":
        signal = None
        if "refid" not in currentTag.attrs:
            signal = "No 'refid' in `ref` tag attributes of file documentation. Attributes were: {}".format(
                currentTag.attrs
            )
        else:
            refid = currentTag.attrs["refid"]
            if refid not in textRoot.node_by_refid:
                signal = "Found unknown 'refid' of [{}] in file level documentation.".format(refid)
            else:
                currentTag.string = ":ref:`{}`".format(textRoot.node_by_refid[refid].link_name)

        if signal:
            # << verboseBuild
            utils.verbose_log(signal, utils.AnsiColors.BOLD_YELLOW)
    else:
        ctr = 0
        for child in children:
            c_prefix = None
            c_postfix = None
            if ctr > 0 and child.name == "para":
                c_prefix = "\n{}".format(indent)

            walk(textRoot, child, level, c_prefix, c_postfix)

            ctr += 1


def convertDescriptionToRST(textRoot, fileNode, soupTag, heading):
    if soupTag.para:
        children = soupTag.findChildren(recursive=False)
        for child in children:
            walk(textRoot, child, 0, None, "\n")
        contents = soupTag.get_text()

        if not heading:
            return contents

        start = textwrap.dedent('''
            {heading}
            {heading_mark}
        '''.format(heading=heading, heading_mark=configs.SUB_SECTION_HEADING))
        return "{}{}".format(start, contents)
    else:
        return ""


def getFileBriefAndDetailedRST(textRoot, fileNode):
    node_xml_contents = utils.nodeCompoundXMLContents(fileNode)
    if not node_xml_contents:
        return "", ""

    try:
        node_soup = BeautifulSoup(node_xml_contents, "lxml-xml")
    except:
        utils.fancyError("Unable to parse [{}] xml using BeautifulSoup".format(fileNode.name))

    try:
        # In the file xml definitions, things such as enums or defines are listed inside
        # of <sectiondef> tags, which may have some nested <briefdescription> or
        # <detaileddescription> tags.  So as long as we make sure not to search
        # recursively, then the following will extract the file descriptions only
        # process the brief description if provided
        brief      = node_soup.doxygen.compounddef.find_all("briefdescription", recursive=False)
        brief_desc = ""
        if len(brief) == 1:
            brief = brief[0]
            # Empty descriptions will usually get parsed as a single newline, which we
            # want to ignore ;)
            if not brief.get_text().isspace():
                brief_desc = convertDescriptionToRST(textRoot, fileNode, brief, None)

        # process the detailed description if provided
        detailed      = node_soup.doxygen.compounddef.find_all("detaileddescription", recursive=False)
        detailed_desc = ""
        if len(detailed) == 1:
            detailed = detailed[0]
            if not detailed.get_text().isspace():
                detailed_desc = convertDescriptionToRST(textRoot, fileNode, detailed, "Detailed Description")

        return brief_desc, detailed_desc
    except:
        utils.fancyError(
            "Could not acquire soup.doxygen.compounddef; likely not a doxygen xml file."
        )