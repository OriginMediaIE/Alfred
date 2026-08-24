#import <Cocoa/Cocoa.h>
#import <WebKit/WebKit.h>

@interface OMAppDelegate : NSObject <NSApplicationDelegate, WKNavigationDelegate>
@property(nonatomic, strong) NSWindow *window;
@property(nonatomic, strong) WKWebView *webView;
@property(nonatomic, strong) NSView *statusView;
@property(nonatomic, strong) NSTextField *statusLabel;
@property(nonatomic, strong) NSProgressIndicator *spinner;
@property(nonatomic, strong) NSTask *serverProcess;
@property(nonatomic, strong) NSTimer *readinessTimer;
@property(nonatomic, strong) NSURL *serverURL;
@property(nonatomic, copy) NSString *installDirectory;
@property(nonatomic, copy) NSString *logPath;
@property(nonatomic) BOOL ownsServer;
@property(nonatomic) NSInteger readinessAttempts;
@end

@implementation OMAppDelegate

- (void)applicationDidFinishLaunching:(NSNotification *)notification {
    if (![self configureRuntime]) {
        return;
    }
    [self buildMenus];
    [self buildWindow];
    [self.window makeKeyAndOrderFront:nil];
    [NSApp activateIgnoringOtherApps:YES];
    [self connectOrStartServer];
}

- (BOOL)applicationShouldTerminateAfterLastWindowClosed:(NSApplication *)sender {
    return YES;
}

- (void)applicationWillTerminate:(NSNotification *)notification {
    [self.readinessTimer invalidate];
    [self stopOwnedServer];
}

- (BOOL)configureRuntime {
    NSDictionary *info = NSBundle.mainBundle.infoDictionary;
    NSString *directory = info[@"OMInstallDirectory"];
    NSString *port = info[@"OMServerPort"];
    if (directory.length == 0 || port.length == 0) {
        [self showFatalError:@"The application bundle is missing its local service configuration."];
        return NO;
    }

    self.installDirectory = directory.stringByExpandingTildeInPath;
    self.serverURL = [NSURL URLWithString:[NSString stringWithFormat:@"http://127.0.0.1:%@", port]];
    self.logPath = [directory stringByAppendingPathComponent:@"data/logs/native-app.log"];
    return self.serverURL != nil;
}

- (void)buildWindow {
    WKWebViewConfiguration *configuration = [[WKWebViewConfiguration alloc] init];
    configuration.websiteDataStore = WKWebsiteDataStore.defaultDataStore;
    configuration.applicationNameForUserAgent = @"OMAutomateNative/1.0";

    NSRect frame = NSMakeRect(0, 0, 1280, 820);
    self.webView = [[WKWebView alloc] initWithFrame:frame configuration:configuration];
    self.webView.navigationDelegate = self;
    self.webView.autoresizingMask = NSViewWidthSizable | NSViewHeightSizable;
    self.webView.hidden = YES;

    self.statusView = [[NSView alloc] initWithFrame:frame];
    self.statusView.wantsLayer = YES;
    self.statusView.layer.backgroundColor = [NSColor colorWithRed:0.067 green:0.075 blue:0.094 alpha:1].CGColor;
    self.statusView.autoresizingMask = NSViewWidthSizable | NSViewHeightSizable;

    self.spinner = [[NSProgressIndicator alloc] initWithFrame:NSMakeRect(0, 0, 24, 24)];
    self.spinner.style = NSProgressIndicatorStyleSpinning;
    self.spinner.controlSize = NSControlSizeRegular;
    [self.spinner startAnimation:nil];

    self.statusLabel = [NSTextField labelWithString:@"Starting OM Automate..."];
    self.statusLabel.textColor = [NSColor colorWithRed:0.851 green:0.871 blue:0.910 alpha:1];
    self.statusLabel.font = [NSFont systemFontOfSize:15 weight:NSFontWeightMedium];
    self.statusLabel.alignment = NSTextAlignmentCenter;

    NSStackView *stack = [NSStackView stackViewWithViews:@[self.spinner, self.statusLabel]];
    stack.orientation = NSUserInterfaceLayoutOrientationVertical;
    stack.alignment = NSLayoutAttributeCenterX;
    stack.spacing = 16;
    stack.translatesAutoresizingMaskIntoConstraints = NO;
    [self.statusView addSubview:stack];
    [NSLayoutConstraint activateConstraints:@[
        [stack.centerXAnchor constraintEqualToAnchor:self.statusView.centerXAnchor],
        [stack.centerYAnchor constraintEqualToAnchor:self.statusView.centerYAnchor],
        [self.statusLabel.widthAnchor constraintLessThanOrEqualToConstant:520]
    ]];

    NSView *content = [[NSView alloc] initWithFrame:frame];
    [content addSubview:self.webView];
    [content addSubview:self.statusView];

    self.window = [[NSWindow alloc]
        initWithContentRect:frame
        styleMask:NSWindowStyleMaskTitled | NSWindowStyleMaskClosable |
                  NSWindowStyleMaskMiniaturizable | NSWindowStyleMaskResizable |
                  NSWindowStyleMaskFullSizeContentView
        backing:NSBackingStoreBuffered
        defer:NO];
    self.window.title = @"OM Automate";
    self.window.minSize = NSMakeSize(900, 620);
    self.window.contentView = content;
    [self.window center];
}

- (void)buildMenus {
    NSMenu *menuBar = [[NSMenu alloc] init];

    NSMenuItem *appItem = [[NSMenuItem alloc] init];
    NSMenu *appMenu = [[NSMenu alloc] initWithTitle:@"OM Automate"];
    [appMenu addItemWithTitle:@"About OM Automate" action:@selector(orderFrontStandardAboutPanel:) keyEquivalent:@""];
    [appMenu addItem:NSMenuItem.separatorItem];
    [appMenu addItemWithTitle:@"Quit OM Automate" action:@selector(terminate:) keyEquivalent:@"q"];
    appItem.submenu = appMenu;
    [menuBar addItem:appItem];

    NSMenuItem *editItem = [[NSMenuItem alloc] init];
    NSMenu *editMenu = [[NSMenu alloc] initWithTitle:@"Edit"];
    [editMenu addItemWithTitle:@"Undo" action:@selector(undo:) keyEquivalent:@"z"];
    [editMenu addItemWithTitle:@"Redo" action:@selector(redo:) keyEquivalent:@"Z"];
    [editMenu addItem:NSMenuItem.separatorItem];
    [editMenu addItemWithTitle:@"Cut" action:@selector(cut:) keyEquivalent:@"x"];
    [editMenu addItemWithTitle:@"Copy" action:@selector(copy:) keyEquivalent:@"c"];
    [editMenu addItemWithTitle:@"Paste" action:@selector(paste:) keyEquivalent:@"v"];
    [editMenu addItemWithTitle:@"Select All" action:@selector(selectAll:) keyEquivalent:@"a"];
    editItem.submenu = editMenu;
    [menuBar addItem:editItem];

    NSMenuItem *viewItem = [[NSMenuItem alloc] init];
    NSMenu *viewMenu = [[NSMenu alloc] initWithTitle:@"View"];
    [viewMenu addItemWithTitle:@"Reload" action:@selector(reloadPage:) keyEquivalent:@"r"];
    [viewMenu addItem:NSMenuItem.separatorItem];
    [viewMenu addItemWithTitle:@"Actual Size" action:@selector(actualSize:) keyEquivalent:@"0"];
    [viewMenu addItemWithTitle:@"Zoom In" action:@selector(zoomIn:) keyEquivalent:@"+"];
    [viewMenu addItemWithTitle:@"Zoom Out" action:@selector(zoomOut:) keyEquivalent:@"-"];
    viewItem.submenu = viewMenu;
    [menuBar addItem:viewItem];

    NSMenuItem *windowItem = [[NSMenuItem alloc] init];
    NSMenu *windowMenu = [[NSMenu alloc] initWithTitle:@"Window"];
    [windowMenu addItemWithTitle:@"Minimize" action:@selector(performMiniaturize:) keyEquivalent:@"m"];
    [windowMenu addItemWithTitle:@"Zoom" action:@selector(performZoom:) keyEquivalent:@""];
    windowItem.submenu = windowMenu;
    [menuBar addItem:windowItem];

    NSApp.mainMenu = menuBar;
}

- (void)connectOrStartServer {
    __weak typeof(self) weakSelf = self;
    [self checkReadiness:^(BOOL ready) {
        if (ready) {
            [weakSelf loadApplication];
        } else {
            [weakSelf startServer];
        }
    }];
}

- (void)startServer {
    NSString *launcher = [self.installDirectory stringByAppendingPathComponent:@"start-macos.sh"];
    if (![NSFileManager.defaultManager isExecutableFileAtPath:launcher]) {
        [self showStartupFailure:@"The local launcher is missing or is not executable."];
        return;
    }

    NSString *logDirectory = self.logPath.stringByDeletingLastPathComponent;
    NSError *error = nil;
    [NSFileManager.defaultManager createDirectoryAtPath:logDirectory
                            withIntermediateDirectories:YES
                                             attributes:@{NSFilePosixPermissions: @0700}
                                                  error:&error];
    if (error) {
        [self showStartupFailure:[NSString stringWithFormat:@"The log directory could not be created: %@", error.localizedDescription]];
        return;
    }
    if (![NSFileManager.defaultManager fileExistsAtPath:self.logPath]) {
        [NSFileManager.defaultManager createFileAtPath:self.logPath contents:nil attributes:@{NSFilePosixPermissions: @0600}];
    }

    NSFileHandle *log = [NSFileHandle fileHandleForWritingAtPath:self.logPath];
    [log seekToEndOfFile];

    NSTask *process = [[NSTask alloc] init];
    process.executableURL = [NSURL fileURLWithPath:@"/bin/bash"];
    process.arguments = @[launcher];
    process.currentDirectoryURL = [NSURL fileURLWithPath:self.installDirectory];
    NSMutableDictionary *environment = [NSProcessInfo.processInfo.environment mutableCopy];
    environment[@"ODYSSEUS_NO_OPEN"] = @"1";
    environment[@"ODYSSEUS_PORT"] = self.serverURL.port.stringValue;
    environment[@"PATH"] = @"/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin";
    process.environment = environment;
    process.standardOutput = log;
    process.standardError = log;

    __weak typeof(self) weakSelf = self;
    process.terminationHandler = ^(NSTask *task) {
        dispatch_async(dispatch_get_main_queue(), ^{
            if (weakSelf.ownsServer && task.terminationStatus != 0 && weakSelf.webView.hidden) {
                [weakSelf showStartupFailure:@"The private service stopped before the app was ready."];
            }
        });
    };

    if (![process launchAndReturnError:&error]) {
        [self showStartupFailure:[NSString stringWithFormat:@"The private service could not start: %@", error.localizedDescription]];
        return;
    }
    self.serverProcess = process;
    self.ownsServer = YES;
    [self beginReadinessPolling];
}

- (void)beginReadinessPolling {
    self.readinessAttempts = 0;
    [self.readinessTimer invalidate];
    self.readinessTimer = [NSTimer scheduledTimerWithTimeInterval:1
                                                           target:self
                                                         selector:@selector(pollReadiness:)
                                                         userInfo:nil
                                                          repeats:YES];
}

- (void)pollReadiness:(NSTimer *)timer {
    self.readinessAttempts += 1;
    self.statusLabel.stringValue = self.readinessAttempts > 20
        ? @"Preparing private services. First launch can take a few minutes..."
        : @"Starting private services...";
    __weak typeof(self) weakSelf = self;
    [self checkReadiness:^(BOOL ready) {
        if (ready) {
            [timer invalidate];
            [weakSelf loadApplication];
        } else if (weakSelf.readinessAttempts >= 300) {
            [timer invalidate];
            [weakSelf showStartupFailure:@"OM Automate did not become ready within five minutes."];
        }
    }];
}

- (void)checkReadiness:(void (^)(BOOL ready))completion {
    NSURL *healthURL = [self.serverURL URLByAppendingPathComponent:@"api/ready"];
    NSMutableURLRequest *request = [NSMutableURLRequest requestWithURL:healthURL];
    request.timeoutInterval = 2;
    [[NSURLSession.sharedSession dataTaskWithRequest:request
                                  completionHandler:^(NSData *data, NSURLResponse *response, NSError *error) {
        NSInteger status = [(NSHTTPURLResponse *)response statusCode];
        dispatch_async(dispatch_get_main_queue(), ^{
            completion(status >= 200 && status < 400);
        });
    }] resume];
}

- (void)loadApplication {
    [self.readinessTimer invalidate];
    self.statusLabel.stringValue = @"Opening your private workspace...";
    [self.webView loadRequest:[NSURLRequest requestWithURL:self.serverURL]];
}

- (void)webView:(WKWebView *)webView didFinishNavigation:(WKNavigation *)navigation {
    self.statusView.hidden = YES;
    self.webView.hidden = NO;
    [self.window makeFirstResponder:self.webView];
}

- (void)webView:(WKWebView *)webView
    decidePolicyForNavigationAction:(WKNavigationAction *)navigationAction
                    decisionHandler:(void (^)(WKNavigationActionPolicy))decisionHandler {
    NSURL *url = navigationAction.request.URL;
    BOOL sameOrigin = [url.host isEqualToString:self.serverURL.host] &&
                      [url.port isEqualToNumber:self.serverURL.port];
    if (sameOrigin) {
        decisionHandler(WKNavigationActionPolicyAllow);
    } else if (navigationAction.navigationType == WKNavigationTypeLinkActivated) {
        [NSWorkspace.sharedWorkspace openURL:url];
        decisionHandler(WKNavigationActionPolicyCancel);
    } else {
        decisionHandler(WKNavigationActionPolicyAllow);
    }
}

- (void)showStartupFailure:(NSString *)message {
    [self.spinner stopAnimation:nil];
    self.statusLabel.maximumNumberOfLines = 5;
    self.statusLabel.lineBreakMode = NSLineBreakByWordWrapping;
    self.statusLabel.stringValue = [NSString stringWithFormat:@"%@\n\nLog: %@", message, self.logPath];
}

- (void)showFatalError:(NSString *)message {
    NSAlert *alert = [[NSAlert alloc] init];
    alert.alertStyle = NSAlertStyleCritical;
    alert.messageText = @"OM Automate could not open";
    alert.informativeText = message;
    [alert runModal];
    [NSApp terminate:nil];
}

- (void)stopOwnedServer {
    if (!self.ownsServer || !self.serverProcess.running) {
        return;
    }
    [self.serverProcess terminate];
    NSDate *deadline = [NSDate dateWithTimeIntervalSinceNow:5];
    while (self.serverProcess.running && deadline.timeIntervalSinceNow > 0) {
        [NSRunLoop.currentRunLoop runUntilDate:[NSDate dateWithTimeIntervalSinceNow:0.05]];
    }
}

- (void)reloadPage:(id)sender { [self.webView reload]; }
- (void)actualSize:(id)sender { self.webView.pageZoom = 1.0; }
- (void)zoomIn:(id)sender { self.webView.pageZoom = MIN(self.webView.pageZoom + 0.1, 2.0); }
- (void)zoomOut:(id)sender { self.webView.pageZoom = MAX(self.webView.pageZoom - 0.1, 0.5); }

@end

int main(int argc, const char *argv[]) {
    @autoreleasepool {
        NSApplication *application = NSApplication.sharedApplication;
        OMAppDelegate *delegate = [[OMAppDelegate alloc] init];
        application.delegate = delegate;
        [application setActivationPolicy:NSApplicationActivationPolicyRegular];
        [application run];
    }
    return 0;
}
