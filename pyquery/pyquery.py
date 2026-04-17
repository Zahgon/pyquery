# Copyright (C) 2008 - Olivier Lauzanne <olauzanne@gmail.com>
#
# Distributed under the BSD license, see LICENSE.txt
from .cssselectpatch import JQueryTranslator
from reprlib import recursive_repr
from urllib.parse import urlencode
from urllib.parse import urljoin
from .openers import url_opener
from .text import extract_text
from copy import deepcopy
from html import escape
from lxml import etree
import lxml.html
import inspect
import itertools
import types
import sys

if sys.version_info >= (3, 12, 0):
    from collections import OrderedDict
else:
    # backward compat. to be able to run doctest with 3.7+. see:
    # https://github.com/gawel/pyquery/issues/249
    # and:
    # https://github.com/python/cpython/blob/3.12/Lib/collections/__init__.py#L272
    from collections import OrderedDict as BaseOrderedDict

    class OrderedDict(BaseOrderedDict):
        @recursive_repr()
        def __repr__(self):
            'od.__repr__() <==> repr(od)'
            if not self:
                return '%s()' % (self.__class__.__name__,)
            return '%s(%r)' % (self.__class__.__name__, dict(self.items()))

basestring = (str, bytes)


def getargspec(func):
    pass


def with_camel_case_alias(func):
    """decorator for methods who required a camelcase alias"""
    pass


_camel_case_aliases = set()


def build_camel_case_aliases(PyQuery):
    """add camelcase aliases to PyQuery"""
    for alias in _camel_case_aliases:
        parts = list(alias.split('_'))
        name = parts[0] + ''.join([p.title() for p in parts[1:]])
        func = getattr(PyQuery, alias)
        f = types.FunctionType(func.__code__, func.__globals__,
                               name, func.__defaults__)
        f.__doc__ = (
            'Alias for :func:`~pyquery.pyquery.PyQuery.%s`') % func.__name__
        setattr(PyQuery, name, f.__get__(None, PyQuery))


def fromstring(context, parser=None, custom_parser=None):
    """use html parser if we don't have clean xml
    """
    if hasattr(context, 'read') and hasattr(context.read, '__call__'):
        meth = 'parse'
    else:
        meth = 'fromstring'
    if custom_parser is None:
        if parser is None:
            try:
                result = getattr(etree, meth)(context)
            except etree.XMLSyntaxError:
                if hasattr(context, 'seek'):
                    context.seek(0)
                result = getattr(lxml.html, meth)(context)
            if isinstance(result, etree._ElementTree):
                return [result.getroot()]
            else:
                return [result]
        elif parser == 'xml':
            custom_parser = getattr(etree, meth)
        elif parser == 'html':
            custom_parser = getattr(lxml.html, meth)
        elif parser == 'html5':
            from lxml.html import html5parser
            custom_parser = getattr(html5parser, meth)
        elif parser == 'soup':
            from lxml.html import soupparser
            custom_parser = getattr(soupparser, meth)
        elif parser == 'html_fragments':
            custom_parser = lxml.html.fragments_fromstring
        else:
            raise ValueError('No such parser: "%s"' % parser)

    result = custom_parser(context)
    if isinstance(result, list):
        return result
    elif isinstance(result, etree._ElementTree):
        return [result.getroot()]
    elif result is not None:
        return [result]
    else:
        return []


def callback(func, *args):
    pass


class NoDefault(object):
    def __repr__(self):
        """clean representation in Sphinx"""
        return '<NoDefault>'


no_default = NoDefault()
del NoDefault


class FlexibleElement(object):
    """property to allow a flexible api"""
    def __init__(self, pget, pset=no_default, pdel=no_default):
        self.pget = pget
        self.pset = pset
        self.pdel = pdel

    def __get__(self, instance, klass):
        class _element(object):
            """real element to support set/get/del attr and item and js call
            style"""
            def __call__(prop, *args, **kwargs):
                return self.pget(instance, *args, **kwargs)
            __getattr__ = __getitem__ = __setattr__ = __setitem__ = __call__

            def __delitem__(prop, name):
                if self.pdel is not no_default:
                    return self.pdel(instance, name)
                else:
                    raise NotImplementedError()
            __delattr__ = __delitem__

            def __repr__(prop):
                return '<flexible_element %s>' % self.pget.__name__
        return _element()

    def __set__(self, instance, value):
        if self.pset is not no_default:
            self.pset(instance, value)
        else:
            raise NotImplementedError()


class PyQuery(list):
    """The main class
    """

    _translator_class = JQueryTranslator

    def __init__(self, *args, **kwargs):
        html = None
        elements = []
        self._base_url = None
        self.parser = kwargs.pop('parser', None)

        if 'parent' in kwargs:
            self._parent = kwargs.pop('parent')
        else:
            self._parent = no_default

        if 'css_translator' in kwargs:
            self._translator = kwargs.pop('css_translator')
        elif self.parser in ('xml',):
            self._translator = self._translator_class(xhtml=True)
        elif self._parent is not no_default:
            self._translator = self._parent._translator
        else:
            self._translator = self._translator_class(xhtml=False)

        self.namespaces = kwargs.pop('namespaces', None)

        if kwargs:
            # specific case to get the dom
            if 'filename' in kwargs:
                html = open(kwargs['filename'],
                            encoding=kwargs.get('encoding'))
            elif 'url' in kwargs:
                url = kwargs.pop('url')
                if 'opener' in kwargs:
                    opener = kwargs.pop('opener')
                    html = opener(url, **kwargs)
                else:
                    html = url_opener(url, kwargs)
                if not self.parser:
                    self.parser = 'html'
                self._base_url = url
            else:
                raise ValueError('Invalid keyword arguments %s' % kwargs)

            elements = fromstring(html, self.parser)
            # close open descriptor if possible
            if hasattr(html, 'close'):
                try:
                    html.close()
                except Exception:
                    pass

        else:
            # get nodes

            # determine context and selector if any
            selector = context = no_default
            length = len(args)
            if length == 1:
                context = args[0]
            elif length == 2:
                selector, context = args
            else:
                raise ValueError(
                    "You can't do that. Please, provide arguments")

            # get context
            if isinstance(context, basestring):
                try:
                    elements = fromstring(context, self.parser)
                except Exception:
                    raise
            elif isinstance(context, self.__class__):
                # copy
                elements = context[:]
            elif isinstance(context, list):
                elements = context
            elif isinstance(context, etree._Element):
                elements = [context]
            else:
                raise TypeError(context)

            # select nodes
            if elements and selector is not no_default:
                xpath = self._css_to_xpath(selector)
                results = []
                for tag in elements:
                    results.extend(
                        tag.xpath(xpath, namespaces=self.namespaces))
                elements = results

        list.__init__(self, elements)

    def _css_to_xpath(self, selector, prefix='descendant-or-self::'):
        pass

    def _copy(self, *args, **kwargs):
        kwargs.setdefault('namespaces', self.namespaces)
        return self.__class__(*args, **kwargs)

    def __call__(self, *args, **kwargs):
        """return a new PyQuery instance
        """
        length = len(args)
        if length == 0:
            raise ValueError('You must provide at least a selector')
        if args[0] == '':
            return self._copy([])
        if (len(args) == 1 and
                isinstance(args[0], str) and
                not args[0].startswith('<')):
            args += (self,)
        result = self._copy(*args, parent=self, **kwargs)
        return result

    # keep original list api prefixed with _
    _append = list.append
    _extend = list.extend

    # improve pythonic api
    def __add__(self, other):
        assert isinstance(other, self.__class__)
        return self._copy(self[:] + other[:])

    def extend(self, other):
        """Extend with another PyQuery object"""
        assert isinstance(other, self.__class__)
        self._extend(other[:])
        return self

    def items(self, selector=None):
        """Iter over elements. Return PyQuery objects:

            >>> d = PyQuery('<div><span>foo</span><span>bar</span></div>')
            >>> [i.text() for i in d.items('span')]
            ['foo', 'bar']
            >>> [i.text() for i in d('span').items()]
            ['foo', 'bar']
            >>> list(d.items('a')) == list(d('a').items())
            True
        """
        pass

    def xhtml_to_html(self):
        """Remove xhtml namespace:

            >>> doc = PyQuery(
            ...         '<html xmlns="http://www.w3.org/1999/xhtml"></html>')
            >>> doc
            [<{http://www.w3.org/1999/xhtml}html>]
            >>> doc.xhtml_to_html()
            [<html>]
        """
        pass

    def remove_namespaces(self):
        """Remove all namespaces:

            >>> doc = PyQuery('<foo xmlns="http://example.com/foo"></foo>')
            >>> doc
            [<{http://example.com/foo}foo>]
            >>> doc.remove_namespaces()
            [<foo>]
        """
        pass

    def __str__(self):
        """xml representation of current nodes::

            >>> xml = PyQuery(
            ...   '<script><![[CDATA[ ]></script>', parser='html_fragments')
            >>> print(str(xml))
            <script>&lt;![[CDATA[ ]&gt;</script>

        """
        return ''.join([etree.tostring(e, encoding=str) for e in self])

    def __unicode__(self):
        """xml representation of current nodes"""
        return u''.join([etree.tostring(e, encoding=str)
                         for e in self])

    def __html__(self):
        """html representation of current nodes::

            >>> html = PyQuery(
            ...   '<script><![[CDATA[ ]></script>', parser='html_fragments')
            >>> print(html.__html__())
            <script><![[CDATA[ ]></script>

        """
        return u''.join([lxml.html.tostring(e, encoding=str)
                         for e in self])

    def __repr__(self):
        r = []
        try:
            for el in self:
                c = el.get('class')
                c = c and '.' + '.'.join(c.split(' ')) or ''
                id = el.get('id')
                id = id and '#' + id or ''
                r.append('<%s%s%s>' % (el.tag, id, c))
            return '[' + (', '.join(r)) + ']'
        except AttributeError:
            return list.__repr__(self)

    @property
    def root(self):
        """return the xml root element
        """
        pass

    @property
    def encoding(self):
        """return the xml encoding of the root element
        """
        pass

    ##############
    # Traversing #
    ##############

    def _filter_only(self, selector, elements, reverse=False, unique=False):
        """Filters the selection set only, as opposed to also including
           descendants.
        """
        pass

    def parent(self, selector=None):
        pass

    def prev(self, selector=None):
        pass

    def next(self, selector=None):
        pass

    def _traverse(self, method):
        pass

    def _traverse_parent_topdown(self):
        pass

    def _next_all(self):
        pass

    @with_camel_case_alias
    def next_all(self, selector=None):
        """
        >>> h = '<span><p class="hello">Hi</p><p>Bye</p><img scr=""/></span>'
        >>> d = PyQuery(h)
        >>> d('p:last').next_all()
        [<img>]
        >>> d('p:last').nextAll()
        [<img>]
        """
        pass

    @with_camel_case_alias
    def next_until(self, selector, filter_=None):
        """
        >>> h = '''
        ... <h2>Greeting 1</h2>
        ... <p>Hello!</p><p>World!</p>
        ... <h2>Greeting 2</h2><p>Bye!</p>
        ... '''
        >>> d = PyQuery(h)
        >>> d('h2:first').nextUntil('h2')
        [<p>, <p>]
        """
        pass

    def _prev_all(self):
        pass

    @with_camel_case_alias
    def prev_all(self, selector=None):
        """
        >>> h = '<span><p class="hello">Hi</p><p>Bye</p><img scr=""/></span>'
        >>> d = PyQuery(h)
        >>> d('p:last').prev_all()
        [<p.hello>]
        >>> d('p:last').prevAll()
        [<p.hello>]
        """
        pass

    def siblings(self, selector=None):
        """
         >>> h = '<span><p class="hello">Hi</p><p>Bye</p><img scr=""/></span>'
         >>> d = PyQuery(h)
         >>> d('.hello').siblings()
         [<p>, <img>]
         >>> d('.hello').siblings('img')
         [<img>]

        """
        pass

    def parents(self, selector=None):
        """
        >>> d = PyQuery('<span><p class="hello">Hi</p><p>Bye</p></span>')
        >>> d('p').parents()
        [<span>]
        >>> d('.hello').parents('span')
        [<span>]
        >>> d('.hello').parents('p')
        []
        """
        pass

    def children(self, selector=None):
        """Filter elements that are direct children of self using optional
        selector:

            >>> d = PyQuery('<span><p class="hello">Hi</p><p>Bye</p></span>')
            >>> d
            [<span>]
            >>> d.children()
            [<p.hello>, <p>]
            >>> d.children('.hello')
            [<p.hello>]
        """
        pass

    def closest(self, selector=None):
        """
        >>> d = PyQuery(
        ...  '<div class="hello"><p>This is a '
        ...  '<strong class="hello">test</strong></p></div>')
        >>> d('strong').closest('div')
        [<div.hello>]
        >>> d('strong').closest('.hello')
        [<strong.hello>]
        >>> d('strong').closest('form')
        []
        """
        pass

    def contents(self):
        """
        Return contents (with text nodes):

            >>> d = PyQuery('hello <b>bold</b>')
            >>> d.contents()  # doctest: +ELLIPSIS
            ['hello ', <Element b at ...>]
        """
        pass

    def filter(self, selector):
        """Filter elements in self using selector (string or function):

            >>> d = PyQuery('<p class="hello">Hi</p><p>Bye</p>')
            >>> d('p')
            [<p.hello>, <p>]
            >>> d('p').filter('.hello')
            [<p.hello>]
            >>> d('p').filter(lambda i: i == 1)
            [<p>]
            >>> d('p').filter(lambda i: PyQuery(this).text() == 'Hi')
            [<p.hello>]
            >>> d('p').filter(lambda i, this: PyQuery(this).text() == 'Hi')
            [<p.hello>]
        """
        pass

    def not_(self, selector):
        """Return elements that don't match the given selector:

            >>> d = PyQuery('<p class="hello">Hi</p><p>Bye</p><div></div>')
            >>> d('p').not_('.hello')
            [<p>]
        """
        pass

    def is_(self, selector):
        """Returns True if selector matches at least one current element, else
        False:

            >>> d = PyQuery('<p class="hello"><span>Hi</span></p><p>Bye</p>')
            >>> d('p').eq(0).is_('.hello')
            True

            >>> d('p').eq(0).is_('span')
            False

            >>> d('p').eq(1).is_('.hello')
            False

        ..
        """
        pass

    def find(self, selector):
        """Find elements using selector traversing down from self:

            >>> m = '<p><span><em>Whoah!</em></span></p><p><em> there</em></p>'
            >>> d = PyQuery(m)
            >>> d('p').find('em')
            [<em>, <em>]
            >>> d('p').eq(1).find('em')
            [<em>]
        """
        pass

    def eq(self, index):
        """Return PyQuery of only the element with the provided index::

            >>> d = PyQuery('<p class="hello">Hi</p><p>Bye</p><div></div>')
            >>> d('p').eq(0)
            [<p.hello>]
            >>> d('p').eq(1)
            [<p>]
            >>> d('p').eq(2)
            []

        ..
        """
        pass

    def each(self, func):
        """apply func on each nodes
        """
        pass

    def map(self, func):
        """Returns a new PyQuery after transforming current items with func.

        func should take two arguments - 'index' and 'element'.  Elements can
        also be referred to as 'this' inside of func::

            >>> d = PyQuery('<p class="hello">Hi there</p><p>Bye</p><br />')
            >>> d('p').map(lambda i, e: PyQuery(e).text())
            ['Hi there', 'Bye']

            >>> d('p').map(lambda i, e: len(PyQuery(this).text()))
            [8, 3]

            >>> d('p').map(lambda i, e: PyQuery(this).text().split())
            ['Hi', 'there', 'Bye']

        """
        pass

    @property
    def length(self):
        pass

    def size(self):
        pass

    def end(self):
        """Break out of a level of traversal and return to the parent level.

            >>> m = '<p><span><em>Whoah!</em></span></p><p><em> there</em></p>'
            >>> d = PyQuery(m)
            >>> d('p').eq(1).find('em').end().end()
            [<p>, <p>]
        """
        pass

    ##############
    # Attributes #
    ##############
    def attr(self, *args, **kwargs):
        """Attributes manipulation
        """
        pass

    @with_camel_case_alias
    def remove_attr(self, name):
        """Remove an attribute::

            >>> d = PyQuery('<div id="myid"></div>')
            >>> d.remove_attr('id')
            [<div>]
            >>> d.removeAttr('id')
            [<div>]

        ..
        """
        pass

    attr = FlexibleElement(pget=attr, pdel=remove_attr)

    #######
    # CSS #
    #######
    def height(self, value=no_default):
        """set/get height of element
        """
        pass

    def width(self, value=no_default):
        """set/get width of element
        """
        pass

    @with_camel_case_alias
    def has_class(self, name):
        """Return True if element has class::

            >>> d = PyQuery('<div class="myclass"></div>')
            >>> d.has_class('myclass')
            True
            >>> d.hasClass('myclass')
            True

        ..
        """
        pass

    @with_camel_case_alias
    def add_class(self, value):
        """Add a css class to elements::

            >>> d = PyQuery('<div></div>')
            >>> d.add_class('myclass')
            [<div.myclass>]
            >>> d.addClass('myclass')
            [<div.myclass>]

        ..
        """
        pass

    @with_camel_case_alias
    def remove_class(self, value):
        """Remove a css class to elements::

            >>> d = PyQuery('<div class="myclass"></div>')
            >>> d.remove_class('myclass')
            [<div>]
            >>> d.removeClass('myclass')
            [<div>]

        ..
        """
        pass

    @with_camel_case_alias
    def toggle_class(self, value):
        """Toggle a css class to elements

            >>> d = PyQuery('<div></div>')
            >>> d.toggle_class('myclass')
            [<div.myclass>]
            >>> d.toggleClass('myclass')
            [<div>]

        """
        pass

    def css(self, *args, **kwargs):
        """css attributes manipulation
        """
        pass

    css = FlexibleElement(pget=css, pset=css)

    ###################
    # CORE UI EFFECTS #
    ###################
    def hide(self):
        """Add display:none to elements style:

            >>> print(PyQuery('<div style="display:none;"/>').hide())
            <div style="display: none"/>

        """
        pass

    def show(self):
        """Add display:block to elements style:

            >>> print(PyQuery('<div />').show())
            <div style="display: block"/>

        """
        pass

    ########
    # HTML #
    ########
    def val(self, value=no_default):
        """Set the attribute value::

            >>> d = PyQuery('<input />')
            >>> d.val('Youhou')
            [<input>]

        Get the attribute value::

            >>> d.val()
            'Youhou'

        Set the selected values for a `select` element with the `multiple`
        attribute::

            >>> d = PyQuery('''
            ...             <select multiple>
            ...                 <option value="you"><option value="hou">
            ...             </select>
            ...             ''')
            >>> d.val(['you', 'hou'])
            [<select>]

        Get the selected values for a `select` element with the `multiple`
        attribute::

            >>> d.val()
            ['you', 'hou']

        """
        pass

    def html(self, value=no_default, **kwargs):
        """Get or set the html representation of sub nodes.

        Get the text value::

            >>> d = PyQuery('<div><span>toto</span></div>')
            >>> print(d.html())
            <span>toto</span>

        Extra args are passed to ``lxml.etree.tostring``::

            >>> d = PyQuery('<div><span></span></div>')
            >>> print(d.html())
            <span/>
            >>> print(d.html(method='html'))
            <span></span>

        Set the text value::

            >>> d.html('<span>Youhou !</span>')
            [<div>]
            >>> print(d)
            <div><span>Youhou !</span></div>
        """
        pass

    @with_camel_case_alias
    def outer_html(self, method="html"):
        """Get the html representation of the first selected element::

            >>> d = PyQuery('<div><span class="red">toto</span> rocks</div>')
            >>> print(d('span'))
            <span class="red">toto</span> rocks
            >>> print(d('span').outer_html())
            <span class="red">toto</span>
            >>> print(d('span').outerHtml())
            <span class="red">toto</span>

            >>> S = PyQuery('<p>Only <b>me</b> & myself</p>')
            >>> print(S('b').outer_html())
            <b>me</b>

        ..
        """
        pass

    def text(self, value=no_default, **kwargs):
        """Get or set the text representation of sub nodes.

        Get the text value::

            >>> doc = PyQuery('<div><span>toto</span><span>tata</span></div>')
            >>> print(doc.text())
            tototata
            >>> doc = PyQuery('''<div><span>toto</span>
            ...               <span>tata</span></div>''')
            >>> print(doc.text())
            toto tata

        Get the text value, without squashing newlines::

            >>> doc = PyQuery('''<div><span>toto</span>
            ...               <span>tata</span></div>''')
            >>> print(doc.text(squash_space=False))
            toto
            tata

        Set the text value::

            >>> doc.text('Youhou !')
            [<div>]
            >>> print(doc)
            <div>Youhou !</div>

        """
        pass

    ################
    # Manipulating #
    ################

    def _get_root(self, value):
        if isinstance(value, basestring):
            root = fromstring(u'<root>' + value + u'</root>',
                              self.parser)[0]
        elif isinstance(value, etree._Element):
            root = self._copy(value)
        elif isinstance(value, PyQuery):
            root = value
        else:
            raise TypeError(
                'Value must be string, PyQuery or Element. Got %r' % value)
        if hasattr(root, 'text') and isinstance(root.text, basestring):
            root_text = root.text
        else:
            root_text = ''
        return root, root_text

    def append(self, value):
        """append value to each nodes
        """
        root, root_text = self._get_root(value)
        for i, tag in enumerate(self):
            if len(tag) > 0:  # if the tag has children
                last_child = tag[-1]
                if not last_child.tail:
                    last_child.tail = ''
                last_child.tail += root_text
            else:
                if not tag.text:
                    tag.text = ''
                tag.text += root_text
            if i > 0:
                root = deepcopy(list(root))
            tag.extend(root)
        return self

    @with_camel_case_alias
    def append_to(self, value):
        """append nodes to value
        """
        pass

    def prepend(self, value):
        """prepend value to nodes
        """
        pass

    @with_camel_case_alias
    def prepend_to(self, value):
        """prepend nodes to value
        """
        pass

    def after(self, value):
        """add value after nodes
        """
        pass

    @with_camel_case_alias
    def insert_after(self, value):
        """insert nodes after value
        """
        pass

    def before(self, value):
        """insert value before nodes
        """
        pass

    @with_camel_case_alias
    def insert_before(self, value):
        """insert nodes before value
        """
        pass

    def wrap(self, value):
        """A string of HTML that will be created on the fly and wrapped around
        each target:

            >>> d = PyQuery('<span>youhou</span>')
            >>> d.wrap('<div></div>')
            [<div>]
            >>> print(d)
            <div><span>youhou</span></div>

        """
        pass

    @with_camel_case_alias
    def wrap_all(self, value):
        """Wrap all the elements in the matched set into a single wrapper
        element::

            >>> d = PyQuery('<div><span>Hey</span><span>you !</span></div>')
            >>> print(d('span').wrap_all('<div id="wrapper"></div>'))
            <div id="wrapper"><span>Hey</span><span>you !</span></div>

            >>> d = PyQuery('<div><span>Hey</span><span>you !</span></div>')
            >>> print(d('span').wrapAll('<div id="wrapper"></div>'))
            <div id="wrapper"><span>Hey</span><span>you !</span></div>

        ..
        """
        pass

    @with_camel_case_alias
    def replace_with(self, value):
        """replace nodes by value:

            >>> doc = PyQuery("<html><div /></html>")
            >>> node = PyQuery("<span />")
            >>> child = doc.find('div')
            >>> child.replace_with(node)
            [<div>]
            >>> print(doc)
            <html><span/></html>

        """
        pass

    @with_camel_case_alias
    def replace_all(self, expr):
        """replace nodes by expr
        """
        pass

    def clone(self):
        """return a copy of nodes
        """
        pass

    def empty(self):
        """remove nodes content
        """
        pass

    def remove(self, expr=no_default):
        """Remove nodes:

             >>> h = (
             ... '<div>Maybe <em>she</em> does <strong>NOT</strong> know</div>'
             ... )
             >>> d = PyQuery(h)
             >>> d('strong').remove()
             [<strong>]
             >>> print(d)
             <div>Maybe <em>she</em> does  know</div>
        """
        pass

    class Fn(object):
        """Hook for defining custom function (like the jQuery.fn):

        .. sourcecode:: python

         >>> fn = lambda: this.map(lambda i, el: PyQuery(this).outerHtml())
         >>> PyQuery.fn.listOuterHtml = fn
         >>> S = PyQuery(
         ...   '<ol>   <li>Coffee</li>   <li>Tea</li>   <li>Milk</li>   </ol>')
         >>> S('li').listOuterHtml()
         ['<li>Coffee</li>', '<li>Tea</li>', '<li>Milk</li>']

        """
        def __setattr__(self, name, func):
            def fn(self, *args, **kwargs):
                pass
            fn.__name__ = name
            setattr(PyQuery, name, fn)
    fn = Fn()

    ########
    # AJAX #
    ########

    @with_camel_case_alias
    def serialize_array(self):
        """Serialize form elements as an array of dictionaries, whose structure
        mirrors that produced by the jQuery API. Notably, it does not handle
        the deprecated `keygen` form element.

            >>> d = PyQuery('<form><input name="order" value="spam"></form>')
            >>> d.serialize_array() == [{'name': 'order', 'value': 'spam'}]
            True
            >>> d.serializeArray() == [{'name': 'order', 'value': 'spam'}]
            True
        """
        pass

    def serialize(self):
        """Serialize form elements as a URL-encoded string.

            >>> h = (
            ... '<form><input name="order" value="spam">'
            ... '<input name="order2" value="baked beans"></form>'
            ... )
            >>> d = PyQuery(h)
            >>> d.serialize()
            'order=spam&order2=baked%20beans'
        """
        pass

    #####################################################
    # Additional methods that are not in the jQuery API #
    #####################################################

    @with_camel_case_alias
    def serialize_pairs(self):
        """Serialize form elements as an array of 2-tuples conventional for
        typical URL-parsing operations in Python.

            >>> d = PyQuery('<form><input name="order" value="spam"></form>')
            >>> d.serialize_pairs()
            [('order', 'spam')]
            >>> d.serializePairs()
            [('order', 'spam')]
        """
        pass

    @with_camel_case_alias
    def serialize_dict(self):
        """Serialize form elements as an ordered dictionary. Multiple values
        corresponding to the same input name are concatenated into one list.

            >>> d = PyQuery('''<form>
            ...             <input name="order" value="spam">
            ...             <input name="order" value="eggs">
            ...             <input name="order2" value="ham">
            ...             </form>''')
            >>> d.serialize_dict()
            OrderedDict({'order': ['spam', 'eggs'], 'order2': 'ham'})
            >>> d.serializeDict()
            OrderedDict({'order': ['spam', 'eggs'], 'order2': 'ham'})
        """
        pass

    @property
    def base_url(self):
        """Return the url of current html document or None if not available.
        """
        pass

    def make_links_absolute(self, base_url=None):
        """Make all links absolute.
        """
        pass


build_camel_case_aliases(PyQuery)
