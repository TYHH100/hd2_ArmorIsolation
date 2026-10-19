// A real unloadable module for the production startup reference-lifetime test.
extern "C" __declspec(dllexport) unsigned startup_fixture_value() {
    return 42;
}
