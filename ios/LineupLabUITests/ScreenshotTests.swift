import XCTest

/// Drives the real app and attaches full-resolution screenshots for the App Store listing
/// (run: xcodebuild test ... -only-testing:LineupLabUITests; export with xcresulttool).
final class ScreenshotTests: XCTestCase {
    override func setUp() { continueAfterFailure = true }

    private func shot(_ app: XCUIApplication, _ name: String) {
        let a = XCTAttachment(screenshot: app.screenshot())
        a.name = name
        a.lifetime = .keepAlways
        add(a)
    }

    func testSignedOutScreens() {
        let app = XCUIApplication()
        app.launch()
        // the welcome screen (signed out)
        XCTAssertTrue(app.staticTexts["The Daily Drive"].waitForExistence(timeout: 30))
        sleep(2)
        shot(app, "01-welcome")
        // the Daily Drive, as a guest
        app.staticTexts["The Daily Drive"].tap()
        let kickoff = app.webViews.buttons["Kickoff"]
        XCTAssertTrue(kickoff.waitForExistence(timeout: 60))
        sleep(3)
        shot(app, "02-drive-intro")
        kickoff.tap()
        sleep(6)                                   // 3-second snap count, then the play clock
        shot(app, "03-drive-play")
    }
}
