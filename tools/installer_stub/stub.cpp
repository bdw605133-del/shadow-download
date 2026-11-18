// SHADOW MODEL self-extracting installer stub.
// Compiled with MSVC (x64). Reads the private SHADOWSFX payload appended by
// tools/package_release.py, extracts it to the per-user application folder,
// creates a Start Menu shortcut and launches ShadowAI.exe.
//
// This source contains no application binaries or models; it only installs
// the verified payload that is appended to it at packaging time.

#include <windows.h>
#include <shlobj.h>
#include <objbase.h>
#include <cstdint>
#include <cstdio>
#include <cstring>
#include <string>
#include <vector>

namespace {

const char MAGIC[16] = {'S','H','A','D','O','W','S','F','X','v','1','\0','\0','\0','\0','\0'};
constexpr DWORD FOOTER_SIZE = 40;
constexpr DWORD BUFFER_SIZE = 1024 * 1024;

struct Footer {
    char magic[16];
    uint64_t offset;
    uint64_t length;
    uint64_t count;
};

void show_error(const wchar_t* message) {
    MessageBoxW(nullptr, message, L"SHADOW MODEL installer", MB_ICONERROR | MB_OK);
}

bool read_exact(HANDLE file, void* buffer, DWORD size) {
    DWORD read = 0;
    while (read < size) {
        DWORD current = 0;
        if (!ReadFile(file, static_cast<char*>(buffer) + read, size - read, &current, nullptr) || current == 0) {
            return false;
        }
        read += current;
    }
    return true;
}

std::wstring utf8_to_wide(const std::string& value) {
    if (value.empty()) return L"";
    int length = MultiByteToWideChar(CP_UTF8, 0, value.c_str(), static_cast<int>(value.size()), nullptr, 0);
    if (length <= 0) return L"";
    std::wstring result(static_cast<size_t>(length), L'\0');
    MultiByteToWideChar(CP_UTF8, 0, value.c_str(), static_cast<int>(value.size()), &result[0], length);
    return result;
}

bool ensure_directory(const std::wstring& path) {
    if (path.empty()) return false;
    DWORD attributes = GetFileAttributesW(path.c_str());
    if (attributes != INVALID_FILE_ATTRIBUTES) {
        return (attributes & FILE_ATTRIBUTE_DIRECTORY) != 0;
    }
    size_t position = path.find_last_of(L'\\');
    if (position != std::wstring::npos && position > 1) {
        if (!ensure_directory(path.substr(0, position))) return false;
    }
    return CreateDirectoryW(path.c_str(), nullptr) != 0 || GetLastError() == ERROR_ALREADY_EXISTS;
}

bool write_payload_file(HANDLE source, uint64_t length, const std::wstring& destination) {
    std::wstring parent = destination.substr(0, destination.find_last_of(L'\\'));
    if (!ensure_directory(parent)) return false;

    HANDLE output = CreateFileW(
        destination.c_str(), GENERIC_WRITE, FILE_SHARE_READ, nullptr,
        CREATE_ALWAYS, FILE_ATTRIBUTE_NORMAL, nullptr
    );
    if (output == INVALID_HANDLE_VALUE) return false;

    std::vector<char> buffer(BUFFER_SIZE);
    uint64_t remaining = length;
    bool success = true;
    while (remaining > 0) {
        DWORD wanted = static_cast<DWORD>(remaining < BUFFER_SIZE ? remaining : BUFFER_SIZE);
        if (!read_exact(source, buffer.data(), wanted)) { success = false; break; }
        DWORD written = 0;
        if (!WriteFile(output, buffer.data(), wanted, &written, nullptr) || written != wanted) {
            success = false;
            break;
        }
        remaining -= written;
    }
    CloseHandle(output);
    return success;
}

bool create_shortcut(const std::wstring& target, const std::wstring& working_dir) {
    HRESULT hr = CoInitialize(nullptr);
    bool ok = false;
    if (SUCCEEDED(hr) || hr == RPC_E_CHANGED_MODE) {
        IShellLinkW* link = nullptr;
        hr = CoCreateInstance(CLSID_ShellLink, nullptr, CLSCTX_INPROC_SERVER,
                              IID_IShellLinkW, reinterpret_cast<void**>(&link));
        if (SUCCEEDED(hr) && link) {
            link->SetPath(target.c_str());
            link->SetWorkingDirectory(working_dir.c_str());
            link->SetDescription(L"SHADOW MODEL desktop AI assistant");
            IPersistFile* persist = nullptr;
            if (SUCCEEDED(link->QueryInterface(IID_IPersistFile, reinterpret_cast<void**>(&persist))) && persist) {
                wchar_t programs[MAX_PATH] = {0};
                if (SUCCEEDED(SHGetFolderPathW(nullptr, CSIDL_PROGRAMS, nullptr, 0, programs))) {
                    std::wstring lnk = std::wstring(programs) + L"\\SHADOW MODEL.lnk";
                    if (SUCCEEDED(persist->Save(lnk.c_str(), TRUE))) ok = true;
                }
                persist->Release();
            }
            link->Release();
        }
        if (SUCCEEDED(hr) || hr == RPC_E_CHANGED_MODE) CoUninitialize();
    }
    return ok;
}

bool validate_relative_name(const std::string& name) {
    if (name.empty() || name[0] == '/' || name.find('\\') != std::string::npos) return false;
    if (name.find(':') != std::string::npos) return false;
    size_t start = 0;
    while (start <= name.size()) {
        size_t end = name.find('/', start);
        std::string part = name.substr(start, end == std::string::npos ? std::string::npos : end - start);
        if (part == "..") return false;
        if (end == std::string::npos) break;
        start = end + 1;
    }
    return true;
}

} // namespace

int WINAPI wWinMain(HINSTANCE, HINSTANCE, PWSTR, int) {
    wchar_t self[MAX_PATH] = {0};
    GetModuleFileNameW(nullptr, self, MAX_PATH);

    HANDLE file = CreateFileW(self, GENERIC_READ, FILE_SHARE_READ, nullptr, OPEN_EXISTING,
                              FILE_ATTRIBUTE_NORMAL, nullptr);
    if (file == INVALID_HANDLE_VALUE) {
        show_error(L"Could not open the installer file.");
        return 1;
    }

    LARGE_INTEGER file_size;
    if (!GetFileSizeEx(file, &file_size) || file_size.QuadPart < static_cast<LONGLONG>(FOOTER_SIZE)) {
        CloseHandle(file);
        show_error(L"The installer file is incomplete.");
        return 1;
    }

    LARGE_INTEGER footer_position;
    footer_position.QuadPart = file_size.QuadPart - FOOTER_SIZE;
    if (SetFilePointerEx(file, footer_position, nullptr, FILE_BEGIN) == 0) {
        CloseHandle(file);
        show_error(L"Could not read the installer footer.");
        return 1;
    }

    Footer footer{};
    if (!read_exact(file, &footer, FOOTER_SIZE) || std::memcmp(footer.magic, MAGIC, 16) != 0) {
        CloseHandle(file);
        show_error(L"This file is not a valid SHADOW MODEL installer.");
        return 1;
    }
    if (footer.offset == 0 || footer.length == 0 || footer.count == 0 ||
        footer.offset + footer.length != static_cast<uint64_t>(footer_position.QuadPart)) {
        CloseHandle(file);
        show_error(L"The installer payload is corrupted.");
        return 1;
    }

    LARGE_INTEGER payload_position;
    payload_position.QuadPart = static_cast<LONGLONG>(footer.offset);
    if (SetFilePointerEx(file, payload_position, nullptr, FILE_BEGIN) == 0) {
        CloseHandle(file);
        show_error(L"Could not locate the installer payload.");
        return 1;
    }

    wchar_t local_app_data[MAX_PATH] = {0};
    if (FAILED(SHGetFolderPathW(nullptr, CSIDL_LOCAL_APPDATA, nullptr, 0, local_app_data))) {
        CloseHandle(file);
        show_error(L"Could not determine the installation folder.");
        return 1;
    }
    std::wstring install_dir = std::wstring(local_app_data) + L"\\SHADOW MODEL\\ShadowAI";
    if (!ensure_directory(install_dir)) {
        CloseHandle(file);
        show_error(L"Could not create the installation folder.");
        return 1;
    }

    bool ok = true;
    for (uint64_t index = 0; index < footer.count && ok; ++index) {
        uint16_t name_length = 0;
        if (!read_exact(file, &name_length, sizeof(name_length))) { ok = false; break; }
        if (name_length == 0 || name_length > 4096) { ok = false; break; }
        std::vector<char> name_buffer(name_length + 1, 0);
        if (!read_exact(file, name_buffer.data(), name_length)) { ok = false; break; }
        std::string name(name_buffer.data(), name_length);
        if (!validate_relative_name(name)) { ok = false; break; }

        uint64_t data_length = 0;
        if (!read_exact(file, &data_length, sizeof(data_length))) { ok = false; break; }

        std::wstring relative = utf8_to_wide(name);
        for (wchar_t& c : relative) if (c == L'/') c = L'\\';
        std::wstring destination = install_dir + L"\\" + relative;
        ok = write_payload_file(file, data_length, destination);
    }
    CloseHandle(file);

    if (!ok) {
        show_error(L"Installation failed while extracting application files.");
        return 1;
    }

    std::wstring exe = install_dir + L"\\ShadowAI.exe";
    create_shortcut(exe, install_dir);
    ShellExecuteW(nullptr, L"open", exe.c_str(), nullptr, install_dir.c_str(), SW_SHOWNORMAL);
    return 0;
}
