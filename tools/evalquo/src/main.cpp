#include <algorithm>
#include <cstdint>
#include <exception>
#include <filesystem>
#include <iostream>
#include <stdexcept>
#include <string>
#include <unordered_map>
#include <utility>
#include <vector>

#include <storm/io/ArchiveReader.h>
#include <storm/utility/initialize.h>

namespace {

// Reads the single file contained in the given archive as a vector that maps each state to its class.
std::vector<uint64_t> readArchive(std::filesystem::path const& file) {
    auto archiveReader = storm::io::openArchive(file);
    if (!archiveReader.isReadableArchive()) {
        throw std::runtime_error("Unable to read from archive " + file.string() + ".");
    }
    std::vector<uint64_t> result;
    bool foundFile = false;
    for (auto entry : archiveReader) {
        if (!entry.isDir()) {
            if (foundFile) {
                throw std::runtime_error("Multiple files in archive " + file.string() + ".");
            }
            foundFile = true;
            std::cout << "Reading file " << entry.name() << " from archive " << file.string() << "...\n";
            result = entry.toVector<uint64_t>();
        }
    }
    if (!foundFile) {
        throw std::runtime_error("Empty archive " + file.string() + ".");
    }
    std::cout << "Read " << result.size() << " entries:";
    for (uint64_t i = 0; i < std::min<uint64_t>(10, result.size()); ++i) {
        std::cout << " " << result[i];
    }
    if (result.size() > 10) {
        std::cout << " ...";
    }
    std::cout << "\n";

    return result;
}

// Returns whether the first equivalence relation refines the second one, i.e., whether all states with the same
// class in the first input also have the same class in the second input.
// Also yields the index of the first relation, i.e., its number of equivalence classes.
bool refines(std::vector<uint64_t> const& stateToClass1, std::vector<uint64_t> const& stateToClass2, uint64_t& index1) {
    // Maps each class of the first relation to the class of the second relation that contains its states.
    std::unordered_map<uint64_t, uint64_t> classMap;
    bool result = true;
    for (size_t state = 0; state < stateToClass1.size(); ++state) {
        auto const [it, inserted] = classMap.emplace(stateToClass1[state], stateToClass2[state]);
        if (!inserted && it->second != stateToClass2[state]) {
            result = false;
        }
    }
    index1 = classMap.size();
    return result;
}

void compare(std::vector<uint64_t> const& stateToClass1, std::vector<uint64_t> const& stateToClass2) {
    if (stateToClass1.size() != stateToClass2.size()) {
        throw std::runtime_error("State to class vectors have different sizes: " + std::to_string(stateToClass1.size()) + " vs. " +
                                 std::to_string(stateToClass2.size()) + ".");
    }

    // R_1 (R_2) is the equivalence relation induced by the first (second) input.
    uint64_t index1, index2;
    bool const refines12 = refines(stateToClass1, stateToClass2, index1);
    bool const refines21 = refines(stateToClass2, stateToClass1, index2);

    std::cout << "Number of states: " << stateToClass1.size() << ".\n";
    std::cout << "Index of R_1 (number of equivalence classes in quotient 1): " << index1 << ".\n";
    std::cout << "Index of R_2 (number of equivalence classes in quotient 2): " << index2 << ".\n";
    if (refines12 && refines21) {
        std::cout << "Quotient 2 is equal to quotient 1.\n";
    } else if (refines21) {
        std::cout << "Quotient 2 is finer than quotient 1.\n";
    } else if (refines12) {
        std::cout << "Quotient 2 is coarser than quotient 1.\n";
    } else {
        std::cout << "Quotient 2 is incomparable with quotient 1.\n";
    }
}

}  // namespace

int main(int argc, char* argv[]) {
    storm::utility::setUp();

    if (argc != 3) {
        std::cerr << "Unexpected number of arguments. Expected two files.\n";
        return 1;
    }
    try {
        auto stateToClass1 = readArchive(argv[1]);
        auto stateToClass2 = readArchive(argv[2]);
        compare(stateToClass1, stateToClass2);
    } catch (std::exception const& e) {
        std::cerr << "ERROR: " << e.what() << "\n";
        return 1;
    }
    return 0;
}
