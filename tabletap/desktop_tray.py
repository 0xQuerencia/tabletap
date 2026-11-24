"""Optional StatusNotifierItem for desktops with a tray host."""
ITEM_XML = """<node><interface name="org.kde.StatusNotifierItem">
<method name="Activate"><arg type="i" direction="in"/><arg type="i" direction="in"/></method>
<method name="SecondaryActivate"><arg type="i" direction="in"/><arg type="i" direction="in"/></method>
<method name="ContextMenu"><arg type="i" direction="in"/><arg type="i" direction="in"/></method>
<property name="Category" type="s" access="read"/><property name="Id" type="s" access="read"/>
<property name="Title" type="s" access="read"/><property name="Status" type="s" access="read"/>
<property name="IconName" type="s" access="read"/><property name="Menu" type="o" access="read"/>
<property name="ItemIsMenu" type="b" access="read"/><property name="WindowId" type="u" access="read"/>
</interface></node>"""
MENU_XML = """<node><interface name="com.canonical.dbusmenu">
<method name="GetLayout"><arg type="i" direction="in"/><arg type="i" direction="in"/><arg type="as" direction="in"/><arg type="u" direction="out"/><arg type="(ia{sv}av)" direction="out"/></method>
<method name="GetGroupProperties"><arg type="ai" direction="in"/><arg type="as" direction="in"/><arg type="a(ia{sv})" direction="out"/></method>
<method name="GetProperty"><arg type="i" direction="in"/><arg type="s" direction="in"/><arg type="v" direction="out"/></method>
<method name="Event"><arg type="i" direction="in"/><arg type="s" direction="in"/><arg type="v" direction="in"/><arg type="u" direction="in"/></method>
<method name="AboutToShow"><arg type="i" direction="in"/><arg type="b" direction="out"/></method>
<property name="Version" type="u" access="read"/><property name="TextDirection" type="s" access="read"/><property name="Status" type="s" access="read"/>
</interface></node>"""


class Tray:
    def __init__(self, show, pause, stop, quit_app):
        from gi.repository import Gio, GLib
        self.Gio, self.GLib = Gio, GLib
        self.connection = Gio.bus_get_sync(Gio.BusType.SESSION, None)
        self.registered = False
        self.closed = False
        self.actions = {1: ("Open TableTap", show), 2: ("Pause actions", pause),
                        3: ("Stop listening", stop), 4: ("Quit TableTap", quit_app)}
        self.objects = [
            self.connection.register_object("/StatusNotifierItem", Gio.DBusNodeInfo.new_for_xml(ITEM_XML).interfaces[0],
                                            self.item_method, self.item_property, None),
            self.connection.register_object("/Menu", Gio.DBusNodeInfo.new_for_xml(MENU_XML).interfaces[0],
                                            self.menu_method, self.menu_property, None)]
        self.watch = Gio.bus_watch_name_on_connection(self.connection, "org.kde.StatusNotifierWatcher",
                                                      Gio.BusNameWatcherFlags.NONE, self.appeared, self.vanished)

    def appeared(self, *_):
        G, V = self.Gio, self.GLib.Variant
        self.connection.call("org.kde.StatusNotifierWatcher", "/StatusNotifierWatcher",
                             "org.kde.StatusNotifierWatcher", "RegisterStatusNotifierItem",
                             V("(s)", (self.connection.get_unique_name(),)), None,
                             G.DBusCallFlags.NONE, 1500, None, self.registration_done)

    def registration_done(self, connection, result):
        try:
            connection.call_finish(result)
            self.registered = not self.closed
        except self.GLib.Error:
            self.registered = False

    def vanished(self, *_):
        self.registered = False
        if not self.closed:
            self.actions[1][1]()

    def item_property(self, _conn, _sender, _path, _interface, name):
        V = self.GLib.Variant
        return {"Category": V("s", "ApplicationStatus"), "Id": V("s", "tabletap"),
                "Title": V("s", "TableTap"), "Status": V("s", "Active"),
                "IconName": V("s", "audio-input-microphone"), "Menu": V("o", "/Menu"),
                "ItemIsMenu": V("b", False), "WindowId": V("u", 0)}.get(name)

    def item_method(self, _conn, _sender, _path, _interface, name, _params, invocation):
        if name == "SecondaryActivate":
            self.actions[2][1]()
        else:
            self.actions[1][1]()
        invocation.return_value(None)

    def menu_property(self, _conn, _sender, _path, _interface, name):
        V = self.GLib.Variant
        return {"Version": V("u", 3), "TextDirection": V("s", "ltr"), "Status": V("s", "normal")}.get(name)

    def props(self, number):
        V = self.GLib.Variant
        return {"label": V("s", self.actions[number][0]), "enabled": V("b", True),
                "visible": V("b", True)} if number in self.actions else {"children-display": V("s", "submenu")}

    def menu_method(self, _conn, _sender, _path, _interface, name, params, invocation):
        V = self.GLib.Variant
        args = params.unpack()
        if name == "GetLayout":
            number, depth, _ = args
            children = [V("(ia{sv}av)", (n, self.props(n), [])) for n in self.actions] if number == 0 and depth != 0 else []
            invocation.return_value(V("(u(ia{sv}av))", (1, (number, self.props(number), children))))
        elif name == "GetGroupProperties":
            numbers = args[0] or list(self.actions)
            invocation.return_value(V("(a(ia{sv}))", ([(n, self.props(n)) for n in numbers],)))
        elif name == "GetProperty":
            value = self.props(args[0]).get(args[1])
            if value is None:
                invocation.return_dbus_error("com.canonical.dbusmenu.Error", "Unknown property")
            else:
                invocation.return_value(V("(v)", (value,)))
        elif name == "AboutToShow":
            invocation.return_value(V("(b)", (False,)))
        elif name == "Event":
            if args[1] == "clicked" and args[0] in self.actions:
                self.actions[args[0]][1]()
            invocation.return_value(None)

    def close(self):
        self.closed = True
        self.registered = False
        self.Gio.bus_unwatch_name(self.watch)
        for object_id in self.objects:
            self.connection.unregister_object(object_id)
